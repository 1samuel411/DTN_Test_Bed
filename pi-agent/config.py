"""
Pi Agent Configuration.
All settings via environment variables with sensible defaults.
Loaded from pi-agent/.env when present.
"""
import os

# ── DTN ──────────────────────────────────────────────────────────────────────
DTN_NODE_ID        = os.getenv("DTN_NODE_ID",        "dtn://pi-telemetry.dtn/")
DTN_AGENT_TELEM    = os.getenv("DTN_AGENT_TELEM",    "telemetry")
DTN_AGENT_STATUS   = os.getenv("DTN_AGENT_STATUS",   "status")
DTN_DEST_NODE      = os.getenv("DTN_DEST_NODE",      "dtn://mac-ground.dtn/")
DTN_SOCKET_PATH    = os.getenv("DTN_SOCKET_PATH",    "/tmp/ud3tn.socket")
DTN_BUNDLE_LIFETIME_S = int(os.getenv("DTN_BUNDLE_LIFETIME_S", "3600"))

# Mac's IP reachable for DTN (WiFi/LTE path — NOT Ethernet)
MAC_DTN_IP         = os.getenv("MAC_DTN_IP",         "192.168.1.100")
MAC_DTN_PORT       = int(os.getenv("MAC_DTN_PORT",   "4224"))

# ── Management plane ──────────────────────────────────────────────────────────
MGMT_SERVER_IP     = os.getenv("MGMT_SERVER_IP",     "10.0.0.1")   # Mac Ethernet
MGMT_SERVER_PORT   = int(os.getenv("MGMT_SERVER_PORT", "8765"))
MGMT_HEARTBEAT_S   = int(os.getenv("MGMT_HEARTBEAT_S",  "5"))
MGMT_RECONNECT_S   = int(os.getenv("MGMT_RECONNECT_S",  "10"))
MGMT_STATUS_PUSH_S = float(os.getenv("MGMT_STATUS_PUSH_S", "1.0"))

# ── GPS ───────────────────────────────────────────────────────────────────────
# "auto" = scan for u-blox / NMEA device on ttyUSB* / ttyACM*
GPS_SERIAL_PORT    = os.getenv("GPS_SERIAL_PORT",    "auto")
GPS_BAUDRATE       = int(os.getenv("GPS_BAUDRATE",   "115200"))
GPS_READ_INTERVAL_S = float(os.getenv("GPS_READ_INTERVAL_S", "1.0"))
GPS_SEND_FREQUENCY_HZ = float(os.getenv("GPS_SEND_FREQUENCY_HZ", "1.0"))

# ── Interfaces ────────────────────────────────────────────────────────────────
# "auto" = detect at runtime
WIFI_INTERFACE     = os.getenv("WIFI_INTERFACE",     "auto")
LTE_INTERFACE      = os.getenv("LTE_INTERFACE",      "auto")
ETH_INTERFACE      = os.getenv("ETH_INTERFACE",      "auto")
ETH_STATIC_IP      = os.getenv("ETH_STATIC_IP",      "10.0.0.2")

# ── Link manager / experiment mode ───────────────────────────────────────────
DEFAULT_LINK_MODE       = os.getenv("DEFAULT_LINK_MODE",        "auto")   # legacy compat
DEFAULT_EXPERIMENT_MODE = os.getenv("DEFAULT_EXPERIMENT_MODE",  "single_link_wifi")
CONNECTIVITY_CHECK_S    = int(os.getenv("CONNECTIVITY_CHECK_S", "1"))
FAILOVER_THRESHOLD      = int(os.getenv("FAILOVER_THRESHOLD",   "3"))

# Adaptive link selection tuning
PROBE_TIMEOUT_S    = float(os.getenv("PROBE_TIMEOUT_S",    "1.0"))   # per-probe TCP timeout
PROBE_WINDOW       = int(os.getenv("PROBE_WINDOW",         "10"))    # rolling probe history size
EWMA_ALPHA         = float(os.getenv("EWMA_ALPHA",         "0.25"))  # EWMA smoothing factor (lower = slower)
RTT_CEIL_MS        = float(os.getenv("RTT_CEIL_MS",        "2000"))  # RTT treated as worst-case at this value
W_RTT              = float(os.getenv("W_RTT",              "0.35"))  # weight of RTT in link score
W_AVAIL            = float(os.getenv("W_AVAIL",            "0.65"))  # weight of availability in link score
HOLD_TIME_S        = float(os.getenv("HOLD_TIME_S",        "10.0"))  # min seconds between adaptive switches
SCORE_HYSTERESIS   = float(os.getenv("SCORE_HYSTERESIS",   "0.15"))  # min score delta to trigger a switch
ADAPTIVE_WIN_STREAK = int(os.getenv("ADAPTIVE_WIN_STREAK", "3"))
IMMEDIATE_FAILOVER_FAILURES = int(os.getenv("IMMEDIATE_FAILOVER_FAILURES", "2"))

# DTN socket paths (redundant mode uses two separate uD3TN instances)
DTN_SOCKET_PATH_WIFI = os.getenv("DTN_SOCKET_PATH_WIFI", DTN_SOCKET_PATH)
DTN_SOCKET_PATH_LTE  = os.getenv("DTN_SOCKET_PATH_LTE",  DTN_SOCKET_PATH)

# ── Queue ─────────────────────────────────────────────────────────────────────
MAX_QUEUE_SIZE     = int(os.getenv("MAX_QUEUE_SIZE", "1024"))

# ── Identity ──────────────────────────────────────────────────────────────────
DEVICE_ID          = os.getenv("DEVICE_ID", "pi-dtn-01")
