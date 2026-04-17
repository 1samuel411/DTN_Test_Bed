"""
Network Emulation Agent.

Applies per-interface traffic shaping using Linux tc + netem + tbf.
Only ever touches WiFi and LTE interfaces — never Ethernet.

Architecture:
  Egress only (ingress shaping requires ifb which adds complexity).
  For a class demo, egress (outbound from Pi) is sufficient to simulate
  link degradation visible in DTN bundle delivery timing.

Qdisc structure when emulation is active:
  root ──► pfifo_fast (baseline, when no emulation)

  With delay/loss/jitter only:
    root handle 1: ──► netem delay Xms Yms loss Z%

  With bandwidth limit + delay/loss:
    root handle 1: ──► tbf rate Rkbps burst 32kbit latency 400ms
    parent 1:1 handle 10: ──► netem delay Xms Yms loss Z%

  With outage (100% loss):
    root handle 1: ──► netem loss 100%

Tradeoff:
  Egress shaping affects Pi→Mac direction (our DTN send path).
  Ingress shaping (Pi receiving from Mac) is not implemented.
  For failover demos this is sufficient; for two-way impairment, add ingress via ifb.

apply() is idempotent: calling it twice with the same settings is safe.
revert() removes all custom qdiscs, restoring pfifo_fast default.
"""

import logging
import subprocess
from typing import Dict, Optional

from schemas import EmulationSettings

logger = logging.getLogger(__name__)

_PROTECTED = {"eth", "enp", "eno", "lo"}   # prefixes — never impair these


def _is_protected(iface: str) -> bool:
    return any(iface.startswith(p) for p in _PROTECTED)


def _run(cmd: list, check: bool = False) -> subprocess.CompletedProcess:
    logger.debug("tc: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


class NetemAgent:
    def __init__(self) -> None:
        # Stores the last applied settings per interface name
        self._active: Dict[str, EmulationSettings] = {}

    # ── Public API ───────────────────────────────────────────────────────────

    def apply(self, iface: str, settings: EmulationSettings) -> None:
        """Apply emulation settings to an interface. Removes any existing qdisc first."""
        if _is_protected(iface):
            raise ValueError(f"Refusing to impair protected interface: {iface}")

        logger.info(
            "Applying emulation to %s: delay=%dms jitter=%dms loss=%.1f%% "
            "bw=%s outage=%s",
            iface,
            settings.delay_ms,
            settings.jitter_ms,
            settings.loss_percent,
            f"{settings.bandwidth_kbps:.3f}kbps" if settings.bandwidth_kbps else "unlimited",
            settings.outage,
        )

        self._del_root(iface)

        if settings.outage:
            # 100% loss = total outage
            _run(["tc", "qdisc", "add", "dev", iface,
                  "root", "handle", "1:", "netem", "loss", "100%"])
            self._active[iface] = settings
            return

        netem_args = self._build_netem_args(settings)

        if settings.bandwidth_kbps:
            # tbf as root, netem as child
            burst = int(max(32768, settings.bandwidth_kbps * 125))  # 1 RTT of data at rate
            _run([
                "tc", "qdisc", "add", "dev", iface,
                "root", "handle", "1:", "tbf",
                "rate",    f"{settings.bandwidth_kbps:.3f}kbit",
                "burst",   str(burst),
                "latency", "400ms",
            ])
            _run([
                "tc", "qdisc", "add", "dev", iface,
                "parent", "1:1", "handle", "10:",
                "netem",
            ] + netem_args)
        else:
            # netem directly at root
            if netem_args:
                _run([
                    "tc", "qdisc", "add", "dev", iface,
                    "root", "handle", "1:", "netem",
                ] + netem_args)

        self._active[iface] = settings

    def revert(self, iface: str) -> None:
        """Remove all custom qdiscs. Returns interface to pfifo_fast default."""
        if _is_protected(iface):
            raise ValueError(f"Refusing to modify protected interface: {iface}")
        self._del_root(iface)
        self._active.pop(iface, None)
        logger.info("Emulation reverted on %s", iface)

    def current(self, iface: str) -> Optional[EmulationSettings]:
        return self._active.get(iface)

    def status(self) -> dict:
        return {iface: s.model_dump() for iface, s in self._active.items()}

    # ── Internal ─────────────────────────────────────────────────────────────

    @staticmethod
    def _del_root(iface: str) -> None:
        """Delete root qdisc if present. Errors are ignored (none existed)."""
        _run(["tc", "qdisc", "del", "dev", iface, "root"])

    @staticmethod
    def _build_netem_args(s: EmulationSettings) -> list:
        args = []
        if s.delay_ms > 0:
            args += ["delay", f"{s.delay_ms}ms"]
            if s.jitter_ms > 0:
                args += [f"{s.jitter_ms}ms", "distribution", "normal"]
        if s.loss_percent > 0:
            args += ["loss", f"{s.loss_percent:.2f}%"]
        return args
