"""
Pi Agent entry point.

Starts all services as asyncio tasks:
  gps_reader   → reads NMEA, emits telemetry + status events
  link_manager → monitors WiFi/LTE, manages routing, fires link events
  dtn_sender   → pulls from queue, sends via uD3TN AAP
  mgmt_client  → WebSocket client to Mac config server over Ethernet

Services communicate via:
  QueueManager   – GPS reader → DTN sender (bounded FIFO)
  asyncio.Event  – link_manager → dtn_sender (link restore signal)
  Direct calls   – mgmt_client → link_manager / netem_agent / gps_reader
"""

import asyncio
import logging
import os
import pathlib
import signal
import sys
from typing import Optional

# Load local .env for repo-based startup and deployment.
try:
    from dotenv import load_dotenv
    import pathlib
    _local     = pathlib.Path(__file__).parent / ".env"
    if _local.exists():
        load_dotenv(_local)
except ImportError:
    pass

from config import (
    CONNECTIVITY_CHECK_S, DEFAULT_EXPERIMENT_MODE, DEFAULT_LINK_MODE, DEVICE_ID,
    DTN_NODE_ID, ETH_INTERFACE, FAILOVER_THRESHOLD,
    GPS_BAUDRATE, GPS_READ_INTERVAL_S, GPS_SEND_FREQUENCY_HZ, GPS_SERIAL_PORT,
    LTE_INTERFACE, MAC_DTN_IP, MAC_DTN_PORT, MAX_QUEUE_SIZE,
    MGMT_SERVER_IP, WIFI_INTERFACE,
)
from schemas import (
    ClearQueueCommand, EmulationSettings,
    PiStatusReport, RevertEmulationCommand,
    SetBaudrateCommand, SetEmulationCommand, SetExperimentModeCommand,
    SetGpsSendFrequencyCommand, SetLinkManagerConfigCommand, SetModeCommand,
)
from gps_reader.gps_reader import GPSReader
from queue_manager.queue_manager import QueueManager
from dtn_sender.dtn_sender import DTNSender
from link_manager.link_manager import LinkManager
from netem_agent.netem_agent import NetemAgent
from mgmt_client.mgmt_client import MgmtClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("pi-agent")
ENV_PATH = pathlib.Path(__file__).parent / ".env"


def _write_env_updates(path: pathlib.Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)

    missing = [key for key in updates if key not in seen]
    if missing and new_lines and new_lines[-1].strip():
        new_lines.append("")
    for key in missing:
        new_lines.append(f"{key}={updates[key]}")
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


async def main() -> None:
    logger.info("Pi agent starting. device_id=%s node_id=%s", DEVICE_ID, DTN_NODE_ID)

    # ── Shared state objects ─────────────────────────────────────────────────
    queue   = QueueManager(max_size=MAX_QUEUE_SIZE)
    netem   = NetemAgent()

    link_mgr = LinkManager(
        mac_dtn_ip        = MAC_DTN_IP,
        mac_dtn_port      = MAC_DTN_PORT,
        check_interval    = CONNECTIVITY_CHECK_S,
        failover_threshold = FAILOVER_THRESHOLD,
        wifi_iface        = WIFI_INTERFACE,
        lte_iface         = LTE_INTERFACE,
        eth_iface         = ETH_INTERFACE,
        initial_mode      = DEFAULT_EXPERIMENT_MODE,
    )

    mgmt: Optional[MgmtClient] = None

    def emit_send_counter(msg):
        if mgmt is None:
            return
        mgmt.publish_dtn_send_counter(msg)

    dtn_sender = DTNSender(
        queue               = queue,
        link_change_event   = link_mgr.link_change_event,
        get_active_link     = lambda: link_mgr.active_link,
        get_experiment_mode = lambda: link_mgr.experiment_mode,
        get_link_scores     = link_mgr.get_scores,
        get_experiment_session_id = lambda: link_mgr.experiment_session_id,
        get_selected_link   = lambda: link_mgr.selected_link,
        get_decision_reason = lambda: link_mgr.decision_reason,
        get_queue_depth     = lambda: queue.depth,
        device_id           = DEVICE_ID,
        emit_send_counter   = emit_send_counter,
    )

    def get_link_state():
        """Called by GPS reader to tag each telemetry message."""
        return (link_mgr.experiment_mode, link_mgr.active_link, queue.depth)

    async def emit(msg):
        """GPS reader callback — enqueues message."""
        accepted = queue.put_nowait(msg)
        if not accepted:
            logger.debug("Message not queued (queue full or closed): %s", type(msg).__name__)

    gps = GPSReader(
        emit_cb        = emit,
        get_link_state = get_link_state,
        serial_port    = GPS_SERIAL_PORT,
        baudrate       = GPS_BAUDRATE,
        read_interval  = GPS_READ_INTERVAL_S,
        send_frequency_hz = GPS_SEND_FREQUENCY_HZ,
    )

    # ── Command handlers (called by mgmt_client) ─────────────────────────────

    def on_set_experiment_mode(cmd: SetExperimentModeCommand):
        link_mgr.set_experiment_mode(cmd.mode)

    def on_set_mode(cmd: SetModeCommand):
        link_mgr.set_mode(cmd.mode)   # legacy — delegates to set_experiment_mode

    def on_set_emulation(cmd: SetEmulationCommand):
        targets = []
        if cmd.interface_role in ("wifi", "both"):
            targets.append(("wifi", link_mgr.wifi_interface))
        if cmd.interface_role in ("lte", "both"):
            targets.append(("lte", link_mgr.lte_interface))

        applied_any = False
        for role, iface in targets:
            if not iface:
                logger.warning("Cannot set emulation: %s interface not detected", role)
                continue
            netem.apply(iface, cmd.settings)
            applied_any = True

        if not applied_any:
            logger.warning("Cannot set emulation: no target interfaces available (%s)", cmd.interface_role)

    def on_revert(cmd: RevertEmulationCommand):
        targets = []
        if cmd.interface_role in ("wifi", "both"):
            targets.append(("wifi", link_mgr.wifi_interface))
        if cmd.interface_role in ("lte", "both"):
            targets.append(("lte", link_mgr.lte_interface))

        reverted_any = False
        for role, iface in targets:
            if not iface:
                logger.warning("Cannot revert emulation: %s interface not detected", role)
                continue
            netem.revert(iface)
            reverted_any = True

        if not reverted_any:
            logger.warning("Cannot revert emulation: no target interfaces available (%s)", cmd.interface_role)

    def on_set_baudrate(cmd: SetBaudrateCommand):
        asyncio.create_task(gps.change_baudrate(cmd.baudrate))

    def on_set_gps_send_frequency(cmd: SetGpsSendFrequencyCommand):
        asyncio.create_task(gps.change_send_frequency(cmd.hz))

    def on_clear_queue(cmd: ClearQueueCommand):
        n = queue.clear()
        logger.info("Queue cleared on operator command: %d messages removed", n)

    async def restart_agent() -> None:
        await asyncio.sleep(1.0)
        logger.info("Restarting Pi agent process after runtime config update")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def on_set_link_manager_config(cmd: SetLinkManagerConfigCommand):
        updates: dict[str, str] = {}
        if cmd.probe_timeout_s is not None:
            updates["PROBE_TIMEOUT_S"] = str(float(cmd.probe_timeout_s))
        if cmd.rtt_ceil_ms is not None:
            updates["RTT_CEIL_MS"] = str(float(cmd.rtt_ceil_ms))
        if not updates:
            logger.info("No link-manager runtime config values supplied")
            return

        for key, value in updates.items():
            os.environ[key] = value
        _write_env_updates(ENV_PATH, updates)
        link_mgr.set_runtime_config(
            probe_timeout_s=cmd.probe_timeout_s,
            rtt_ceil_ms=cmd.rtt_ceil_ms,
        )
        logger.info(
            "Persisted link-manager config to %s restart_agent=%s",
            ENV_PATH,
            cmd.restart_agent,
        )
        if cmd.restart_agent:
            asyncio.create_task(restart_agent())

    # ── Status report builder ────────────────────────────────────────────────

    def build_status() -> PiStatusReport:
        ls   = link_mgr.status()
        qs   = queue.stats()
        dtns = dtn_sender.counters
        wifi_iface = ls["wifi_interface"]
        lte_iface  = ls["lte_interface"]
        return PiStatusReport(
            device_id              = DEVICE_ID,
            wifi_interface         = wifi_iface,
            wifi_ip                = ls["wifi_ip"],
            wifi_up                = ls["wifi_up"],
            wifi_reachable         = ls["wifi_reachable"],
            lte_interface          = lte_iface,
            lte_ip                 = ls["lte_ip"],
            lte_up                 = ls["lte_up"],
            lte_reachable          = ls["lte_reachable"],
            eth_interface          = ls["eth_interface"],
            eth_ip                 = ls["eth_ip"],
            eth_up                 = ls["eth_up"],
            gps_device             = gps.device,
            gps_connected          = gps.connected,
            gps_fix_state          = gps.fix_state,
            gps_baudrate           = gps.baudrate,
            gps_send_frequency_hz  = gps.send_frequency_hz,
            queue_depth            = qs["depth"],
            queue_full             = qs["is_full"],
            queue_dropped          = qs["dropped_count"],
            active_mode            = ls["experiment_mode"],
            active_link            = ls["active_link"],
            experiment_mode        = ls["experiment_mode"],
            experiment_session_id  = ls["experiment_session_id"],
            selected_link          = ls["selected_link"],
            decision_reason        = ls["decision_reason"],
            last_failover_ts       = ls["last_failover_ts"],
            last_failover_direction = ls["last_failover_direction"],
            wifi_score             = ls["wifi_score"],
            lte_score              = ls["lte_score"],
            wifi_ewma_rtt_ms       = ls["wifi_ewma_rtt_ms"],
            lte_ewma_rtt_ms        = ls["lte_ewma_rtt_ms"],
            wifi_probe_loss_rate   = ls["wifi_probe_loss_rate"],
            lte_probe_loss_rate    = ls["lte_probe_loss_rate"],
            probe_timeout_s        = ls["probe_timeout_s"],
            rtt_ceil_ms            = ls["rtt_ceil_ms"],
            dtn_bytes_sent_wifi    = dtns["bytes_wifi"],
            dtn_bytes_sent_lte     = dtns["bytes_lte"],
            dtn_bundles_sent_wifi  = dtns["bundles_wifi"],
            dtn_bundles_sent_lte   = dtns["bundles_lte"],
            dtn_send_failures_wifi = dtns["failures_wifi"],
            dtn_send_failures_lte  = dtns["failures_lte"],
            dtn_send_retries_wifi  = dtns["retries_wifi"],
            dtn_send_retries_lte   = dtns["retries_lte"],
            telemetry_generated    = gps.generated_count,
            telemetry_enqueued     = qs["total_enqueued"],
            emulation_wifi         = netem.current(wifi_iface) if wifi_iface else None,
            emulation_lte          = netem.current(lte_iface)  if lte_iface  else None,
        )

    mgmt = MgmtClient(
        get_status              = build_status,
        on_set_mode             = on_set_mode,
        on_set_experiment_mode  = on_set_experiment_mode,
        on_set_emulation        = on_set_emulation,
        on_revert               = on_revert,
        on_set_baudrate         = on_set_baudrate,
        on_set_gps_send_frequency = on_set_gps_send_frequency,
        on_clear_queue          = on_clear_queue,
        on_set_link_manager_config = on_set_link_manager_config,
    )

    # ── Graceful shutdown ────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig):
        logger.info("Signal %s received. Shutting down.", sig.name)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    # ── Run all services ─────────────────────────────────────────────────────
    tasks = [
        asyncio.create_task(link_mgr.run(),  name="link_manager"),
        asyncio.create_task(dtn_sender.run(), name="dtn_sender"),
        asyncio.create_task(gps.run(),        name="gps_reader"),
        asyncio.create_task(mgmt.run(),       name="mgmt_client"),
        asyncio.create_task(stop_event.wait(), name="shutdown_watcher"),
    ]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    logger.info("Stopping all services")
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    gps.stop()
    link_mgr.stop()
    dtn_sender.stop()
    mgmt.stop()
    logger.info("Pi agent stopped cleanly")


if __name__ == "__main__":
    asyncio.run(main())
