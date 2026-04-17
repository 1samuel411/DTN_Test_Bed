"""
DTN Test Bed MCP server — stdio transport, HTTP client to mac-backend.

Never write to stdout except via MCP (logging must use stderr).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sys
import time
from typing import Any, Literal, Optional

import httpx
from mcp.server.fastmcp import FastMCP

from dtn_mcp.config import (
    api_base_url,
    export_results_default_limit,
    export_results_max_limit,
    http_timeout_seconds,
    load_mcp_env,
    log_level,
    public_config_summary,
    timed_experiment_default_duration_seconds,
    timed_experiment_default_warmup_seconds,
)

load_mcp_env()

logger = logging.getLogger("dtn_mcp")

ExperimentMode = Literal["single_link_wifi", "single_link_lte", "adaptive", "redundant"]
InterfaceRole = Literal["wifi", "lte", "both"]

mcp = FastMCP(
    "DTN Testbed",
    instructions=(
        "Controls the live DTN testbed via the Mac REST API: experiment modes, "
        "netem emulation, metrics, and CSV export of recent telemetry results."
    ),
)


def _client() -> httpx.Client:
    return httpx.Client(base_url=api_base_url(), timeout=http_timeout_seconds())


def _get(path: str, params: Optional[dict[str, Any]] = None) -> Any:
    with _client() as c:
        r = c.get(path, params=params)
        r.raise_for_status()
        return r.json()


def _post(path: str, body: dict[str, Any]) -> Any:
    with _client() as c:
        r = c.post(path, json=body)
        r.raise_for_status()
        return r.json()


@mcp.tool()
def dtn_get_api_base() -> str:
    """Return the Mac API base URL in use (from .env / environment). Use to verify config."""
    return api_base_url()


@mcp.tool()
def dtn_get_config() -> str:
    """Return active MCP configuration (timeouts, limits, log level, API URL). Loaded from dtn-mcp/.env."""
    return json.dumps(public_config_summary(), indent=2)


@mcp.tool()
def dtn_get_status() -> str:
    """Fetch latest Pi status from GET /api/status (links, experiment mode, queue, emulation)."""
    try:
        return json.dumps(_get("/api/status"), indent=2)
    except Exception as e:
        logger.exception("dtn_get_status")
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
def dtn_get_telemetry_metrics() -> str:
    """Rolling window metrics: PDR, latency, deadline success/miss vs configured deadline_ms."""
    try:
        return json.dumps(_get("/api/metrics"), indent=2)
    except Exception as e:
        logger.exception("dtn_get_telemetry_metrics")
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
def dtn_get_experiment_metrics() -> str:
    """Per-session experiment metrics (latency percentiles, delivery, duplicates, etc.)."""
    try:
        return json.dumps(_get("/api/metrics/experiment"), indent=2)
    except Exception as e:
        logger.exception("dtn_get_experiment_metrics")
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
def dtn_get_experiment_distribution() -> str:
    """Grouped outcomes by experiment mode + emulation profile."""
    try:
        return json.dumps(_get("/api/metrics/experiment/distribution"), indent=2)
    except Exception as e:
        logger.exception("dtn_get_experiment_distribution")
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
def dtn_set_experiment_mode(mode: ExperimentMode) -> str:
    """Set Pi experiment mode (starts a new experiment_session_id on the Pi)."""
    try:
        body = {"cmd": "set_experiment_mode", "mode": mode}
        return json.dumps(_post("/api/command", body), indent=2)
    except Exception as e:
        logger.exception("dtn_set_experiment_mode")
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
def dtn_set_emulation(
    interface_role: InterfaceRole,
    delay_ms: int = 0,
    jitter_ms: int = 0,
    loss_percent: float = 0.0,
    bandwidth_kbps: Optional[float] = None,
    outage: bool = False,
) -> str:
    """Apply netem-style emulation to wifi, lte, or both interfaces on the Pi."""
    try:
        settings: dict[str, Any] = {
            "delay_ms": delay_ms,
            "jitter_ms": jitter_ms,
            "loss_percent": loss_percent,
            "outage": outage,
        }
        if bandwidth_kbps is not None:
            settings["bandwidth_kbps"] = bandwidth_kbps
        body = {
            "cmd": "set_emulation",
            "interface_role": interface_role,
            "settings": settings,
        }
        return json.dumps(_post("/api/command", body), indent=2)
    except Exception as e:
        logger.exception("dtn_set_emulation")
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
def dtn_revert_emulation(interface_role: InterfaceRole) -> str:
    """Remove emulation for the given interface role."""
    try:
        body = {"cmd": "revert_emulation", "interface_role": interface_role}
        return json.dumps(_post("/api/command", body), indent=2)
    except Exception as e:
        logger.exception("dtn_revert_emulation")
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
def dtn_clear_queue() -> str:
    """Clear the Pi telemetry queue (mgmt command)."""
    try:
        body = {"cmd": "clear_queue"}
        return json.dumps(_post("/api/command", body), indent=2)
    except Exception as e:
        logger.exception("dtn_clear_queue")
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
def dtn_set_link_manager_config(
    probe_timeout_s: Optional[float] = None,
    rtt_ceil_ms: Optional[float] = None,
    restart_agent: bool = True,
) -> str:
    """
    Configure Pi link-manager timeout/scoring settings and optionally restart the Pi agent.

    Use this before long-delay profiles such as Lunar/P-05. The Pi agent persists supplied
    values to its .env, applies them to the running LinkManager, and self-restarts when
    restart_agent is true.
    """
    try:
        if probe_timeout_s is None and rtt_ceil_ms is None:
            return json.dumps(
                {
                    "ok": False,
                    "error": "provide at least one of probe_timeout_s or rtt_ceil_ms",
                },
                indent=2,
            )
        body: dict[str, Any] = {
            "cmd": "set_link_manager_config",
            "restart_agent": restart_agent,
        }
        if probe_timeout_s is not None:
            body["probe_timeout_s"] = probe_timeout_s
        if rtt_ceil_ms is not None:
            body["rtt_ceil_ms"] = rtt_ceil_ms
        return json.dumps(_post("/api/command", body), indent=2)
    except Exception as e:
        logger.exception("dtn_set_link_manager_config")
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
def dtn_export_results_csv(limit: Optional[int] = None) -> str:
    """
    Return recent accepted telemetry results as CSV (paste into Sheets/Excel).
    Columns match RecentTelemetryResult from the Mac API.
    Default row count comes from DTN_EXPORT_RESULTS_DEFAULT_LIMIT in .env.
    """
    try:
        n = export_results_default_limit() if limit is None else limit
        cap = export_results_max_limit()
        rows = _get("/api/results", params={"limit": max(1, min(n, cap))})
        if not isinstance(rows, list):
            return "ts,error\n0,unexpected response type"
        if not rows:
            return "ts,experiment_session_id,packet_id,sequence_number,experiment_mode,selected_link,winning_link,latency_ms,queue_wait_ms,queue_depth_at_send,altitude,had_duplicate\n"
        buf = io.StringIO()
        fieldnames = list(rows[0].keys())
        w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            if isinstance(row, dict):
                w.writerow(row)
        return buf.getvalue()
    except Exception as e:
        logger.exception("dtn_export_results_csv")
        return f"error\n{str(e)!r}"


@mcp.tool()
def dtn_run_timed_experiment(
    mode: ExperimentMode,
    duration_seconds: Optional[float] = None,
    warmup_seconds: Optional[float] = None,
) -> str:
    """
    Set experiment mode, wait warmup, run for duration, return telemetry + experiment metrics JSON.
    Does not change emulation; call dtn_set_emulation before this if needed.
    Omitted duration/warmup use DTN_TIMED_DEFAULT_* from .env.
    """
    try:
        w = timed_experiment_default_warmup_seconds() if warmup_seconds is None else warmup_seconds
        d = timed_experiment_default_duration_seconds() if duration_seconds is None else duration_seconds
        _post("/api/command", {"cmd": "set_experiment_mode", "mode": mode})
        time.sleep(max(0.0, w))
        time.sleep(max(0.0, d))
        out = {
            "mode": mode,
            "warmup_seconds": w,
            "duration_seconds": d,
            "telemetry_metrics": _get("/api/metrics"),
            "experiment_metrics": _get("/api/metrics/experiment"),
        }
        return json.dumps(out, indent=2)
    except Exception as e:
        logger.exception("dtn_run_timed_experiment")
        return json.dumps({"ok": False, "error": str(e)})


def _logging_level() -> int:
    name = log_level()
    return getattr(logging, name, logging.INFO) if hasattr(logging, name) else logging.INFO


def main() -> None:
    load_mcp_env()
    logging.basicConfig(
        level=_logging_level(),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        # Normal when stopping `python -m dtn_mcp` manually; Claude Desktop closes stdin instead.
        sys.exit(0)


if __name__ == "__main__":
    main()
