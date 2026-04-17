"""
Link Manager.

Controls which interface is used for DTN data-plane traffic.
Manages OS routing to MAC_DTN_IP without touching the Ethernet management interface.

Experiment modes:
  single_link_wifi  — route DTN traffic via WiFi only (baseline)
  single_link_lte   — route DTN traffic via LTE only (baseline)
  adaptive          — performance-scored link selection with EWMA + hold timer
  redundant         — both links kept active; DTN sender handles dual-send

Legacy modes (still accepted for backward compat):
  wifi_only → single_link_wifi
  lte_only  → single_link_lte
  auto      → adaptive

Adaptive scoring:
  Each link is scored 0.0–1.0 every probe cycle using:
    score = W_RTT * rtt_score + W_AVAIL * availability_score
  where rtt_score = max(0, 1 - ewma_rtt / RTT_CEIL_MS)
        availability_score = 1 - (failed_probes / PROBE_WINDOW)
  EWMA smoothing suppresses transient spikes.
  Switches only when winner leads by ≥ SCORE_HYSTERESIS and HOLD_TIME_S has elapsed.

Failover probe:
  TCP connect to MAC_DTN_IP:MAC_DTN_PORT bound to each interface via SO_BINDTODEVICE.
  RTT measured as elapsed wall time of the TCP connect call.
  Requires CAP_NET_RAW (run pi-agent as root or grant the capability).

Routing (single-link modes):
  Adds a specific /32 host route for MAC_DTN_IP via the active interface.
  Never modifies the default route or any route for the Ethernet management subnet.

Routing (redundant mode):
  Adds /32 routes for BOTH interfaces simultaneously so both uD3TN instances
  (if configured) or both DTN send paths can reach the Mac.
"""

import asyncio
import collections
import logging
import socket
import subprocess
import time
from typing import Dict, Optional

import psutil

from config import (
    ADAPTIVE_WIN_STREAK, EWMA_ALPHA, HOLD_TIME_S, IMMEDIATE_FAILOVER_FAILURES,
    PROBE_TIMEOUT_S, PROBE_WINDOW,
    RTT_CEIL_MS, SCORE_HYSTERESIS, W_AVAIL, W_RTT,
)
from experiment import new_experiment_session_id, normalize_experiment_mode

logger = logging.getLogger(__name__)

# When using auto interface detection, re-scan if LTE/WiFi was missing (modem may enumerate late).
IFACE_REDETECT_INTERVAL_S = 15.0


class LinkManager:
    def __init__(
        self,
        mac_dtn_ip:   str,
        mac_dtn_port: int,
        check_interval: int = 5,
        failover_threshold: int = 3,  # kept for compat; not used in adaptive
        wifi_iface: str = "auto",
        lte_iface:  str = "auto",
        eth_iface:  str = "auto",
        initial_mode: str = "single_link_wifi",
    ) -> None:
        self._mac_dtn_ip       = mac_dtn_ip
        self._mac_dtn_port     = mac_dtn_port
        self._check_interval   = check_interval

        self._wifi_iface_cfg = wifi_iface
        self._lte_iface_cfg  = lte_iface
        self._eth_iface_cfg  = eth_iface

        self._wifi_iface: Optional[str] = None
        self._lte_iface:  Optional[str] = None
        self._eth_iface:  Optional[str] = None

        # Normalise initial mode (accept legacy names)
        self._mode        = normalize_experiment_mode(initial_mode)
        self._active_link = "none"
        self._running     = False
        self._experiment_session_id = new_experiment_session_id()
        self._decision_reason = "baseline"

        # Reachability state (latest probe result)
        self._wifi_reachable = False
        self._lte_reachable  = False

        # ── Adaptive scoring state ────────────────────────────────────────────
        # EWMA RTT per link (ms); None until first successful probe
        self._ewma_rtt: Dict[str, Optional[float]] = {"wifi": None, "lte": None}

        # Rolling window of probe outcomes (True=success, False=fail)
        self._probe_history: Dict[str, collections.deque] = {
            "wifi": collections.deque(maxlen=PROBE_WINDOW),
            "lte":  collections.deque(maxlen=PROBE_WINDOW),
        }

        # Computed scores (0.0–1.0); updated each probe cycle
        self._scores: Dict[str, float] = {"wifi": 0.0, "lte": 0.0}

        # Anti-flapping: timestamp of last link switch
        self._last_switch_ts: float = 0.0
        self._candidate_link: Optional[str] = None
        self._candidate_streak = 0

        # Failover history (for PiStatusReport and event logging)
        self._last_failover_ts:        Optional[float] = None
        self._last_failover_direction: Optional[str]   = None

        # Tracks which /32 routes we've added (so we can remove them cleanly)
        self._active_routes: Dict[str, Optional[str]] = {"wifi": None, "lte": None}

        # Signal to DTN sender that link status changed
        self._link_change_event = asyncio.Event()

        self._last_iface_redetect_ts: float = 0.0

    # ── Public properties ────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def experiment_mode(self) -> str:
        return self._mode

    @property
    def active_link(self) -> str:
        return self._active_link

    @property
    def experiment_session_id(self) -> str:
        return self._experiment_session_id

    @property
    def decision_reason(self) -> str:
        return self._decision_reason

    @property
    def selected_link(self) -> str:
        if self._mode == "redundant":
            return "both"
        if self._active_link in ("wifi", "lte"):
            return self._active_link
        if self._mode == "single_link_lte":
            return "lte"
        return "wifi"

    @property
    def link_available(self) -> bool:
        return self._active_link in ("wifi", "lte") or self._mode == "redundant"

    @property
    def link_change_event(self) -> asyncio.Event:
        return self._link_change_event

    @property
    def wifi_interface(self) -> Optional[str]:
        return self._wifi_iface

    @property
    def lte_interface(self) -> Optional[str]:
        return self._lte_iface

    @property
    def eth_interface(self) -> Optional[str]:
        return self._eth_iface

    @property
    def wifi_reachable(self) -> bool:
        return self._wifi_reachable

    @property
    def lte_reachable(self) -> bool:
        return self._lte_reachable

    def get_scores(self) -> Dict[str, Optional[float]]:
        """Current link scores (0.0–1.0). None if link has no probe history."""
        return {
            "wifi": self._scores["wifi"] if self._probe_history["wifi"] else None,
            "lte":  self._scores["lte"]  if self._probe_history["lte"]  else None,
        }

    def get_ewma_rtt(self) -> Dict[str, Optional[float]]:
        return {"wifi": self._ewma_rtt["wifi"], "lte": self._ewma_rtt["lte"]}

    def get_probe_loss_rates(self) -> Dict[str, Optional[float]]:
        return {
            "wifi": self._probe_loss_rate("wifi"),
            "lte": self._probe_loss_rate("lte"),
        }

    def _iface_ip(self, iface: Optional[str]) -> Optional[str]:
        if not iface:
            return None
        for saddr in psutil.net_if_addrs().get(iface, []):
            if saddr.family == socket.AF_INET:
                return saddr.address
        return None

    @property
    def wifi_ip(self) -> Optional[str]:
        return self._iface_ip(self._wifi_iface)

    @property
    def lte_ip(self) -> Optional[str]:
        return self._iface_ip(self._lte_iface)

    @property
    def eth_ip(self) -> Optional[str]:
        return self._iface_ip(self._eth_iface)

    # ── Mode control ─────────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        """Accept both legacy and new mode names."""
        resolved = normalize_experiment_mode(mode)
        assert resolved in (
            "single_link_wifi", "single_link_lte", "adaptive", "redundant",
        ), f"Unknown experiment mode: {mode}"
        if resolved == self._mode:
            return

        logger.info("Experiment mode: %s → %s", self._mode, resolved)
        self._mode = resolved
        self._experiment_session_id = new_experiment_session_id()
        self._decision_reason = "redundant" if resolved == "redundant" else "baseline"
        self._last_switch_ts = 0.0
        self._candidate_link = None
        self._candidate_streak = 0
        self._link_change_event.set()

    def set_experiment_mode(self, mode: str) -> None:
        self.set_mode(mode)

    def set_runtime_config(
        self,
        probe_timeout_s: float | None = None,
        rtt_ceil_ms: float | None = None,
    ) -> None:
        """Update adaptive probe/scoring tunables without rebuilding the manager."""
        global PROBE_TIMEOUT_S, RTT_CEIL_MS

        if probe_timeout_s is not None:
            PROBE_TIMEOUT_S = float(probe_timeout_s)
        if rtt_ceil_ms is not None:
            RTT_CEIL_MS = float(rtt_ceil_ms)

        # Existing EWMA values were computed under the previous scoring ceiling.
        # Clear the short histories so post-change status reflects fresh probes.
        self._ewma_rtt = {"wifi": None, "lte": None}
        self._probe_history = {
            "wifi": collections.deque(maxlen=PROBE_WINDOW),
            "lte": collections.deque(maxlen=PROBE_WINDOW),
        }
        self._scores = {"wifi": 0.0, "lte": 0.0}
        self._candidate_link = None
        self._candidate_streak = 0
        logger.info(
            "Link manager runtime config updated: PROBE_TIMEOUT_S=%.3f RTT_CEIL_MS=%.1f",
            PROBE_TIMEOUT_S,
            RTT_CEIL_MS,
        )

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        self._detect_interfaces()
        logger.info(
            "Link manager: wifi=%s lte=%s eth=%s mode=%s",
            self._wifi_iface, self._lte_iface, self._eth_iface, self._mode,
        )
        while self._running:
            await self._check_cycle()
            await asyncio.sleep(self._check_interval)

    def stop(self) -> None:
        self._running = False

    # ── Interface detection ──────────────────────────────────────────────────

    def _detect_interfaces(self) -> None:
        ifaces = list(psutil.net_if_stats().keys())

        self._wifi_iface = (
            self._wifi_iface_cfg if self._wifi_iface_cfg != "auto"
            else self._find_wifi(ifaces)
        )
        self._lte_iface = (
            self._lte_iface_cfg if self._lte_iface_cfg != "auto"
            else self._find_lte(ifaces)
        )
        self._eth_iface = (
            self._eth_iface_cfg if self._eth_iface_cfg != "auto"
            else self._find_eth(ifaces)
        )
        logger.info("Interfaces — wifi: %s  lte: %s  eth: %s",
                    self._wifi_iface, self._lte_iface, self._eth_iface)

    @staticmethod
    def _find_wifi(ifaces: list) -> Optional[str]:
        for prefix in ("wlan", "wlp"):
            hits = sorted(i for i in ifaces if i.startswith(prefix))
            if hits:
                return hits[0]
        return None

    @staticmethod
    def _find_lte(ifaces: list) -> Optional[str]:
        skip = (
            "lo", "eth", "enp", "eno", "wlan", "wlp",
            "tun", "docker", "virbr", "br-", "veth", "bond",
        )
        # Prefer common cellular / tethering names before the generic fallback.
        # Many modems use wwan* (QMI/MBIM) or ppp*; omit tailscale*/zt* from fallback
        # so VPN interfaces are not mistaken for LTE.
        for prefix in ("wwan", "ppp", "usb", "rndis", "enx"):
            hits = sorted(i for i in ifaces if i.startswith(prefix))
            if hits:
                return hits[0]
        remainder = sorted(
            i
            for i in ifaces
            if not any(i.startswith(p) for p in skip)
            and not i.startswith("tailscale")
            and not i.startswith("zt")
        )
        return remainder[0] if remainder else None

    @staticmethod
    def _find_eth(ifaces: list) -> Optional[str]:
        for prefix in ("eth", "enp", "eno"):
            hits = sorted(i for i in ifaces if i.startswith(prefix)
                         and not i.startswith("enx"))
            if hits:
                return hits[0]
        return None

    # ── Connectivity / scoring probes ────────────────────────────────────────

    def _iface_up(self, iface: Optional[str]) -> bool:
        if not iface:
            return False
        stats = psutil.net_if_stats()
        return iface in stats and stats[iface].isup

    async def _probe(self, iface: str) -> tuple[bool, Optional[float]]:
        """
        TCP probe to Mac's DTN port bound to a specific interface.
        Returns (reachable: bool, rtt_ms: float | None).
        """
        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, self._tcp_probe_sync, iface),
                timeout=PROBE_TIMEOUT_S + 0.5,  # outer timeout > inner
            )
            return result
        except (asyncio.TimeoutError, Exception) as e:
            logger.debug("Probe %s failed: %s", iface, e)
            return False, None

    def _tcp_probe_sync(self, iface: str) -> tuple[bool, Optional[float]]:
        target_ip = self._resolve_target_ip()
        if not target_ip:
            logger.warning("Probe %s skipped: unable to resolve %s", iface, self._mac_dtn_ip)
            return False, None

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(PROBE_TIMEOUT_S)
        try:
            s.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_BINDTODEVICE,
                (iface + "\0").encode(),
            )
            t0 = time.monotonic()
            s.connect((target_ip, self._mac_dtn_port))
            rtt_ms = (time.monotonic() - t0) * 1000.0
            return True, rtt_ms
        except OSError:
            return False, None
        finally:
            s.close()

    def _resolve_target_ip(self) -> Optional[str]:
        try:
            infos = socket.getaddrinfo(
                self._mac_dtn_ip, self._mac_dtn_port,
                family=socket.AF_INET, type=socket.SOCK_STREAM,
            )
        except socket.gaierror as e:
            logger.warning("Failed to resolve DTN target %s: %s", self._mac_dtn_ip, e)
            return None
        return infos[0][4][0] if infos else None

    def _update_ewma_and_score(self, link: str, reachable: bool, rtt_ms: Optional[float]) -> None:
        """Update EWMA RTT and compute link score after a probe result."""
        self._probe_history[link].append(reachable)

        if reachable and rtt_ms is not None:
            prev = self._ewma_rtt[link]
            self._ewma_rtt[link] = (
                rtt_ms if prev is None
                else EWMA_ALPHA * rtt_ms + (1 - EWMA_ALPHA) * prev
            )

        if not reachable:
            self._scores[link] = 0.0
            return

        history = self._probe_history[link]
        loss_rate = (history.count(False) / len(history)) if history else 0.0

        ewma = self._ewma_rtt[link] or 0.0
        rtt_score  = max(0.0, 1.0 - ewma / RTT_CEIL_MS)
        avail_score = 1.0 - loss_rate

        self._scores[link] = W_RTT * rtt_score + W_AVAIL * avail_score

    def _probe_loss_rate(self, link: str) -> Optional[float]:
        history = self._probe_history[link]
        if not history:
            return None
        return history.count(False) / len(history)

    def _has_recent_failures(self, link: str, count: int) -> bool:
        history = self._probe_history[link]
        if len(history) < count:
            return False
        return list(history)[-count:] == [False] * count

    # ── Main check cycle ─────────────────────────────────────────────────────

    async def _check_cycle(self) -> None:
        now = time.monotonic()
        if (
            now - self._last_iface_redetect_ts >= IFACE_REDETECT_INTERVAL_S
            and (
                (self._wifi_iface_cfg == "auto" and self._wifi_iface is None)
                or (self._lte_iface_cfg == "auto" and self._lte_iface is None)
            )
        ):
            self._last_iface_redetect_ts = now
            self._detect_interfaces()

        # Probe each interface that is physically up
        if self._iface_up(self._wifi_iface):
            ok, rtt = await self._probe(self._wifi_iface)
            self._wifi_reachable = ok
            self._update_ewma_and_score("wifi", ok, rtt)
        else:
            self._wifi_reachable = False
            self._update_ewma_and_score("wifi", False, None)

        if self._iface_up(self._lte_iface):
            ok, rtt = await self._probe(self._lte_iface)
            self._lte_reachable = ok
            self._update_ewma_and_score("lte", ok, rtt)
        else:
            self._lte_reachable = False
            self._update_ewma_and_score("lte", False, None)

        logger.debug(
            "Link check: wifi_reach=%s(score=%.2f) lte_reach=%s(score=%.2f) mode=%s active=%s",
            self._wifi_reachable, self._scores["wifi"],
            self._lte_reachable,  self._scores["lte"],
            self._mode, self._active_link,
        )

        if self._mode == "single_link_wifi":
            self._apply("wifi" if self._wifi_reachable else "none",
                        "single_link_wifi")

        elif self._mode == "single_link_lte":
            self._apply("lte" if self._lte_reachable else "none",
                        "single_link_lte")

        elif self._mode == "adaptive":
            self._adaptive_logic()

        elif self._mode == "redundant":
            self._redundant_logic()

    def _adaptive_logic(self) -> None:
        """
        Score-based link selection with EWMA smoothing and anti-flapping.

        Switching rules:
          1. If only one link is reachable, use it unconditionally.
          2. If both are reachable, only switch if:
             a. HOLD_TIME_S has elapsed since last switch, AND
             b. Winner's score exceeds current link's score by ≥ SCORE_HYSTERESIS.
        """
        if not self._wifi_reachable and not self._lte_reachable:
            self._apply("none", "adaptive_link_down", "adaptive:both-down")
            return

        current = self._active_link
        if (
            current == "wifi" and (
                not self._wifi_reachable or
                self._has_recent_failures("wifi", IMMEDIATE_FAILOVER_FAILURES)
            )
        ):
            next_link = "lte" if self._lte_reachable else "none"
            self._apply(next_link, "adaptive_link_down", "adaptive:wifi-unhealthy")
            return
        if (
            current == "lte" and (
                not self._lte_reachable or
                self._has_recent_failures("lte", IMMEDIATE_FAILOVER_FAILURES)
            )
        ):
            next_link = "wifi" if self._wifi_reachable else "none"
            self._apply(next_link, "adaptive_link_down", "adaptive:lte-unhealthy")
            return

        if not self._lte_reachable:
            self._apply("wifi", "adaptive_link_down", "adaptive:lte-down")
            return
        if not self._wifi_reachable:
            self._apply("lte", "adaptive_link_down", "adaptive:wifi-down")
            return

        now = time.monotonic()
        wifi_score = self._scores["wifi"]
        lte_score  = self._scores["lte"]
        if current not in ("wifi", "lte"):
            # No link yet — pick the best
            best = "wifi" if wifi_score >= lte_score else "lte"
            self._apply(best, "adaptive_score", f"adaptive:initial best={best}")
            return

        best = "wifi" if wifi_score >= lte_score else "lte"
        best_score = wifi_score if best == "wifi" else lte_score
        current_score = wifi_score if current == "wifi" else lte_score

        if best == current or best_score < current_score + SCORE_HYSTERESIS:
            self._candidate_link = None
            self._candidate_streak = 0
            self._decision_reason = "adaptive_score"
            return

        if self._candidate_link == best:
            self._candidate_streak += 1
        else:
            self._candidate_link = best
            self._candidate_streak = 1

        if self._candidate_streak < ADAPTIVE_WIN_STREAK:
            self._decision_reason = "adaptive_hold"
            logger.debug(
                "Adaptive hold: candidate=%s streak=%d/%d current=%s",
                best, self._candidate_streak, ADAPTIVE_WIN_STREAK, current,
            )
            return

        if now - self._last_switch_ts < HOLD_TIME_S:
            self._decision_reason = "adaptive_hold"
            logger.debug(
                "Adaptive hold timer active: candidate=%s current=%s remaining=%.2fs",
                best, current, HOLD_TIME_S - (now - self._last_switch_ts),
            )
            return

        self._apply(
            best,
            "adaptive_score",
            f"adaptive:score-switch {current}={current_score:.2f}→{best}={best_score:.2f}",
        )

    def _redundant_logic(self) -> None:
        """
        In redundant mode the link manager keeps both routes active.
        active_link reports the "best available" for informational purposes only;
        the DTN sender is responsible for dual-send via two uD3TN sockets.
        """
        if self._wifi_reachable and self._lte_reachable:
            new_info = "wifi" if self._scores["wifi"] >= self._scores["lte"] else "lte"
        elif self._wifi_reachable:
            new_info = "wifi"
        elif self._lte_reachable:
            new_info = "lte"
        else:
            new_info = "none"

        if new_info != self._active_link:
            logger.info("Redundant mode: reachability changed → %s", new_info)
            self._active_link = new_info
            self._link_change_event.set()
        self._decision_reason = "redundant"
        reachable_links = []
        if self._wifi_reachable:
            reachable_links.append("wifi")
        if self._lte_reachable:
            reachable_links.append("lte")
        self._set_redundant_routes(reachable_links)

    # ── Route management ─────────────────────────────────────────────────────

    def _apply(self, new_link: str, reason: str, detail: str = "") -> None:
        if new_link == self._active_link:
            self._decision_reason = reason
            return

        old = self._active_link
        logger.info("Link switch: %s → %s  (%s)", old, new_link, detail or reason)
        self._active_link = new_link
        self._last_switch_ts = time.monotonic()
        self._decision_reason = reason
        self._candidate_link = None
        self._candidate_streak = 0

        # Update OS routes for single-link modes
        self._set_single_route(new_link)

        if old != "none" and new_link != "none":
            self._last_failover_ts        = time.time()
            self._last_failover_direction = f"{old}→{new_link}"

        self._link_change_event.set()

    def _set_single_route(self, link: str) -> None:
        """Remove all DTN host routes and add one for the chosen link."""
        for lk in ("wifi", "lte"):
            if self._active_routes[lk]:
                subprocess.run(
                    ["ip", "route", "del", self._active_routes[lk]],
                    capture_output=True,
                )
                self._active_routes[lk] = None

        if link in ("wifi", "lte"):
            self._add_route(link)

    def _ensure_route(self, link: str) -> None:
        """Add route for link if not already present (used in redundant mode)."""
        target_ip = self._resolve_target_ip()
        if not target_ip:
            return
        if self._active_routes[link] == target_ip:
            return  # already present
        self._add_route(link)

    def _set_redundant_routes(self, links: list[str]) -> None:
        """
        Install DTN host routing for redundant mode.

        With two reachable links, use a Linux multipath host route. Two uD3TN
        TCP sessions to the same Mac endpoint can then be spread across the two
        next hops by the kernel instead of being pinned to whichever single
        route was installed last.
        """
        unique_links = [lk for lk in ("wifi", "lte") if lk in links]
        if len(unique_links) <= 1:
            self._set_single_route(unique_links[0] if unique_links else "none")
            return

        target_ip = self._resolve_target_ip()
        if not target_ip:
            logger.warning("Cannot update redundant DTN route: unresolved target %s", self._mac_dtn_ip)
            return

        cmd = ["ip", "route", "replace", target_ip]
        active_links: list[str] = []
        for link in unique_links:
            iface = self._wifi_iface if link == "wifi" else self._lte_iface
            if not iface:
                continue
            cmd.append("nexthop")
            gw = self._get_gateway(iface)
            if gw:
                cmd += ["via", gw]
            cmd += ["dev", iface, "weight", "1"]
            active_links.append(link)

        if len(active_links) <= 1:
            self._set_single_route(active_links[0] if active_links else "none")
            return

        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            for link in ("wifi", "lte"):
                self._active_routes[link] = target_ip if link in active_links else None
            logger.info("DTN route [redundant]: %s via %s", target_ip, ",".join(active_links))
        else:
            logger.warning(
                "Redundant route add failed %s via %s: %s",
                target_ip, ",".join(active_links), r.stderr.strip(),
            )

    def _add_route(self, link: str) -> None:
        iface = self._wifi_iface if link == "wifi" else self._lte_iface
        if not iface:
            return
        target_ip = self._resolve_target_ip()
        if not target_ip:
            logger.warning("Cannot update DTN route: unresolved target %s", self._mac_dtn_ip)
            return

        gw  = self._get_gateway(iface)
        # Use "replace" so stale host routes are corrected automatically.
        # "add" fails with "File exists" and can leave uD3TN pinned to an
        # old next-hop/interface even while probe checks pass.
        cmd = ["ip", "route", "replace", target_ip]
        if gw:
            cmd += ["via", gw]
        cmd += ["dev", iface]

        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            self._active_routes[link] = target_ip
            logger.info("DTN route [%s]: %s via %s (%s)", link, target_ip, iface, gw or "direct")
        else:
            logger.warning("Route add failed [%s] %s via %s: %s",
                           link, target_ip, iface, r.stderr.strip())

    def _get_gateway(self, iface: str) -> Optional[str]:
        try:
            r = subprocess.run(
                ["ip", "route", "show", "dev", iface],
                capture_output=True, text=True,
            )
            for line in r.stdout.splitlines():
                if line.strip().startswith("default"):
                    parts = line.split()
                    if "via" in parts:
                        return parts[parts.index("via") + 1]
        except Exception as e:
            logger.debug("Gateway detect error for %s: %s", iface, e)
        return None

    # ── Status dict ──────────────────────────────────────────────────────────

    def status(self) -> dict:
        scores   = self.get_scores()
        ewma_rtt = self.get_ewma_rtt()
        probe_loss = self.get_probe_loss_rates()
        return {
            "mode":                    self._mode,
            "experiment_mode":         self._mode,
            "experiment_session_id":   self._experiment_session_id,
            "active_link":             self._active_link,
            "selected_link":           self.selected_link,
            "decision_reason":         self._decision_reason,
            "wifi_interface":          self._wifi_iface,
            "wifi_ip":                 self.wifi_ip,
            "wifi_up":                 self._iface_up(self._wifi_iface),
            "wifi_reachable":          self._wifi_reachable,
            "lte_interface":           self._lte_iface,
            "lte_ip":                  self.lte_ip,
            "lte_up":                  self._iface_up(self._lte_iface),
            "lte_reachable":           self._lte_reachable,
            "eth_interface":           self._eth_iface,
            "eth_ip":                  self.eth_ip,
            "eth_up":                  self._iface_up(self._eth_iface),
            "wifi_score":              scores["wifi"],
            "lte_score":               scores["lte"],
            "wifi_ewma_rtt_ms":        ewma_rtt["wifi"],
            "lte_ewma_rtt_ms":         ewma_rtt["lte"],
            "wifi_probe_loss_rate":    probe_loss["wifi"],
            "lte_probe_loss_rate":     probe_loss["lte"],
            "probe_timeout_s":          PROBE_TIMEOUT_S,
            "rtt_ceil_ms":              RTT_CEIL_MS,
            "last_failover_ts":        self._last_failover_ts,
            "last_failover_direction": self._last_failover_direction,
        }
