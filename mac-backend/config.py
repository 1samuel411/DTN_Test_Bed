"""
Mac Backend Configuration.
All settings via environment variables.
Loaded from mac-backend/.env at startup.
"""
import os

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve_db_path(raw: str | None) -> str:
    """Default DB lives under repo `.run/` so /tmp permission issues do not break startup."""
    if not raw or not raw.strip():
        return os.path.normpath(os.path.join(_BACKEND_DIR, "..", ".run", "dtn_testbed.db"))
    p = os.path.expanduser(raw.strip())
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(_BACKEND_DIR, p))


# DTN
DTN_NODE_ID    = os.getenv("DTN_NODE_ID",    "dtn://mac-ground.dtn/")
DTN_SOCKET_PATH = os.getenv("DTN_SOCKET_PATH", "/tmp/ud3tn.socket")
ENABLE_DTN_BRIDGE = os.getenv("ENABLE_DTN_BRIDGE", "true").lower() in {
    "1", "true", "yes", "on"
}

# API Server
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8080"))

# Config Server (management WebSocket — Ethernet only)
# Bind to the Mac's Ethernet interface IP
CONFIG_HOST = os.getenv("CONFIG_HOST", "10.0.0.1")
CONFIG_PORT = int(os.getenv("CONFIG_PORT", "8765"))

# SQLite database path (relative paths are resolved from mac-backend/)
DB_PATH = _resolve_db_path(os.getenv("DB_PATH"))

# Rolling telemetry metric settings
REALTIME_DEADLINE_MS = int(os.getenv("REALTIME_DEADLINE_MS", "2000"))
METRICS_WINDOW_SIZE = int(os.getenv("METRICS_WINDOW_SIZE", "100"))
DEDUP_TTL_S = int(os.getenv("DEDUP_TTL_S", "3600"))
