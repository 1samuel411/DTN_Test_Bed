"""
Load configuration from environment and optional dtn-mcp/.env file.

Process environment wins over .env (override=False) so Claude Desktop / Inspector
can still override single keys when needed.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ENV_PATH = _PACKAGE_ROOT / ".env"


def load_mcp_env() -> None:
    """Load variables from .env into os.environ if not already set."""
    path = os.environ.get("DTN_MCP_ENV_PATH")
    if path:
        p = Path(path).expanduser().resolve()
        if p.is_file():
            load_dotenv(p, override=False)
        return
    if _DEFAULT_ENV_PATH.is_file():
        load_dotenv(_DEFAULT_ENV_PATH, override=False)


def api_base_url() -> str:
    return os.environ.get("DTN_API_BASE", "http://127.0.0.1:8080").rstrip("/")


def http_timeout_seconds() -> float:
    return float(os.environ.get("DTN_HTTP_TIMEOUT_SECONDS", "60"))


def log_level() -> str:
    return os.environ.get("DTN_LOG_LEVEL", "INFO").upper()


def export_results_default_limit() -> int:
    return max(1, int(os.environ.get("DTN_EXPORT_RESULTS_DEFAULT_LIMIT", "200")))


def export_results_max_limit() -> int:
    return max(1, int(os.environ.get("DTN_EXPORT_RESULTS_MAX_LIMIT", "2000")))


def timed_experiment_default_warmup_seconds() -> float:
    return max(0.0, float(os.environ.get("DTN_TIMED_DEFAULT_WARMUP_SECONDS", "5")))


def timed_experiment_default_duration_seconds() -> float:
    return max(0.0, float(os.environ.get("DTN_TIMED_DEFAULT_DURATION_SECONDS", "60")))


def public_config_summary() -> dict[str, str | int | float]:
    """Safe values for dtn_get_config (no secrets)."""
    return {
        "DTN_API_BASE": api_base_url(),
        "DTN_HTTP_TIMEOUT_SECONDS": http_timeout_seconds(),
        "DTN_LOG_LEVEL": log_level(),
        "DTN_EXPORT_RESULTS_DEFAULT_LIMIT": export_results_default_limit(),
        "DTN_EXPORT_RESULTS_MAX_LIMIT": export_results_max_limit(),
        "DTN_TIMED_DEFAULT_WARMUP_SECONDS": timed_experiment_default_warmup_seconds(),
        "DTN_TIMED_DEFAULT_DURATION_SECONDS": timed_experiment_default_duration_seconds(),
        "env_file_loaded": str(_DEFAULT_ENV_PATH) if _DEFAULT_ENV_PATH.is_file() else "",
    }
