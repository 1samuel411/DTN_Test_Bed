# DTN Test Bed — MCP (Model Context Protocol) Reference

This document is a **complete machine- and human-readable specification** of the `dtn-mcp` server: what it is, how it is configured, how it maps to the Mac backend HTTP API, and **every tool** exposed to MCP clients (Claude Desktop, Cursor, MCP Inspector, or custom scripts using the MCP Python client).

**Source of truth in code:** `dtn-mcp/dtn_mcp/server.py`, `dtn-mcp/dtn_mcp/config.py`.  
**Backend API:** `mac-backend/api_server/server.py` (FastAPI). Commands are forwarded to the Pi via the config server WebSocket (`POST /api/command`).

---

## 1. Purpose

The MCP server is a **stdio** bridge: an AI assistant (or automation) talks JSON-RPC over stdin/stdout to the MCP process; the process uses **HTTP** (`httpx`) to call the **Mac backend REST API** that controls the live DTN testbed (Pi link modes, netem emulation, metrics, telemetry results export).

It does **not** implement DTN logic itself—it is a **remote control and observability façade** for the Mac stack.

---

## 2. Architecture

```
[MCP client: Claude / Cursor / Inspector / Python mcp client]
        │ JSON-RPC over stdio (stdout must be MCP-only)
        ▼
[dtn-mcp — FastMCP "DTN Testbed"]
        │ GET/POST HTTP
        ▼
[Mac backend — e.g. http://127.0.0.1:8080]
        │ WebSocket command channel
        ▼
[Pi agent / lab]
```

**Critical constraint:** The server **must not write to stdout** except through the MCP library. **Logging uses stderr** (`logging.basicConfig(..., stream=sys.stderr)`).

**Transport:** `stdio` only (`mcp.run(transport="stdio")`). There is no built-in SSE or HTTP transport in this package.

**Dependencies** (`dtn-mcp/pyproject.toml`): `mcp[cli]>=1.2.0`, `httpx>=0.27.0`, `python-dotenv>=1.0.0`. Python **3.10+**.

**Entry points:**

- `python -m dtn_mcp`
- Console script `dtn-mcp` → `dtn_mcp.server:main`

---

## 3. Server metadata (for MCP clients)

| Field | Value |
|--------|--------|
| **Server name** | `DTN Testbed` (FastMCP constructor) |
| **Instructions (system-facing)** | Controls the live DTN testbed via the Mac REST API: experiment modes, netem emulation, metrics, and CSV export of recent telemetry results. |
| **Package version** | `dtn_mcp.__version__` → `0.1.0` (see `dtn_mcp/__init__.py`) |

---

## 4. Configuration and environment

Configuration is read from **`dtn-mcp/.env`** (if present) via `python-dotenv` with **`override=False`**: variables already set in the **process environment** take precedence over the file. This allows Claude Desktop `env` in `claude_desktop_config.json` to override single keys.

**Alternate env file:** set `DTN_MCP_ENV_PATH` to an absolute path; if that file exists, it is loaded (also `override=False`). If unset, the default is `dtn-mcp/.env` next to `pyproject.toml`.

### 4.1 Environment variables (full list)

| Variable | Default | Purpose |
|----------|---------|---------|
| `DTN_API_BASE` | `http://127.0.0.1:8080` | Mac backend base URL **without trailing slash**. Same idea as frontend `VITE_API_URL` / API port. |
| `DTN_HTTP_TIMEOUT_SECONDS` | `60` | Per-request HTTP timeout (seconds). |
| `DTN_LOG_LEVEL` | `INFO` | Python logging level name (e.g. `DEBUG`, `INFO`). Must match `logging` module attribute names. |
| `DTN_EXPORT_RESULTS_DEFAULT_LIMIT` | `200` | Default row count for `dtn_export_results_csv` when `limit` is omitted. |
| `DTN_EXPORT_RESULTS_MAX_LIMIT` | `2000` | Hard cap: requested `limit` is clamped to `[1, max]`. |
| `DTN_TIMED_DEFAULT_WARMUP_SECONDS` | `5` | Default warmup for `dtn_run_timed_experiment` when `warmup_seconds` is omitted. |
| `DTN_TIMED_DEFAULT_DURATION_SECONDS` | `60` | Default run duration for `dtn_run_timed_experiment` when `duration_seconds` is omitted. |
| `DTN_MCP_ENV_PATH` | (unset) | Optional absolute path to an alternate `.env` file. |

**Tool `dtn_get_config`** returns a JSON object with the resolved values above plus `env_file_loaded` (path string if default `.env` exists, else empty).

---

## 5. HTTP mapping (Mac API)

All requests use the configured `DTN_API_BASE`. Unless noted, successful responses are JSON; tools typically **`json.dumps(..., indent=2)`** and return a **string**.

| MCP usage | Method | Path | Notes |
|-----------|--------|------|--------|
| Status | GET | `/api/status` | 503 if no status yet: `{"error": "no status yet"}`. |
| Rolling metrics | GET | `/api/metrics` | TelemetryMetrics |
| Experiment metrics | GET | `/api/metrics/experiment` | ExperimentMetrics |
| Distribution | GET | `/api/metrics/experiment/distribution` | ExperimentDistributionMetrics |
| Results rows | GET | `/api/results?limit=N` | List of `RecentTelemetryResult` dicts |
| Commands | POST | `/api/command` | JSON body: management command (see §7). Success: typically `{"ok": true}`. |

**Not exposed as MCP tools** (exist on Mac API but have no dedicated tool in `server.py`):  
`GET /api/telemetry`, `GET /api/events`, `GET /api/dtn/counters`, `GET/POST /api/experiment-recording-runs`, `WebSocket /ws`. An AI with only MCP must use **curl or another client** if those are needed, or extend `server.py`.

---

## 6. Shared enums and payload shapes

### 6.1 `ExperimentMode` (MCP / `set_experiment_mode`)

Literal strings:

- `single_link_wifi`
- `single_link_lte`
- `adaptive`
- `redundant`

Setting experiment mode **starts a new `experiment_session_id` on the Pi** (see backend behavior).

### 6.2 `InterfaceRole`

Literal strings:

- `wifi` — apply to WiFi interface role
- `lte` — LTE
- `both` — both

### 6.3 Emulation settings (netem-style)

Used inside `dtn_set_emulation` → POST body `settings` (matches `EmulationSettings` in `mac-backend/shared/schemas.py`):

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `delay_ms` | int | 0 | Added delay |
| `jitter_ms` | int | 0 | Jitter |
| `loss_percent` | float | 0.0 | Loss percentage |
| `bandwidth_kbps` | optional number | omitted | Cap bandwidth when set |
| `outage` | bool | false | Outage flag |

The MCP tool accepts `bandwidth_kbps` as optional float; it is omitted from JSON when `None`.

### 6.4 `RecentTelemetryResult` (CSV columns)

`dtn_export_results_csv` builds CSV from `/api/results` rows. Typical columns (from schema):

- `ts`, `experiment_session_id`, `packet_id`, `sequence_number`, `experiment_mode`, `selected_link`, `winning_link`, `latency_ms`, `queue_wait_ms`, `queue_depth_at_send`, `altitude`, `had_duplicate`

Header row is derived from the **first row’s keys** if the list is non-empty; if the API returns an unexpected type, the tool returns a minimal error CSV.

---

## 7. Management commands (`POST /api/command`)

The MCP tools wrap a subset of commands. The body is always JSON with a `cmd` discriminator.

| `cmd` | Exposed by MCP | Tool |
|-------|----------------|------|
| `set_experiment_mode` | Yes | `dtn_set_experiment_mode`, `dtn_run_timed_experiment` (internal) |
| `set_emulation` | Yes | `dtn_set_emulation` |
| `revert_emulation` | Yes | `dtn_revert_emulation` |
| `clear_queue` | Yes | `dtn_clear_queue` |
| `set_link_manager_config` | Yes | `dtn_set_link_manager_config` |
| `set_mode` | No | (Pi link mode: `wifi_only` / `lte_only` / `auto` — different from experiment mode) |
| `set_baudrate` | No | |
| `set_gps_send_frequency` | No | |

To send an unsupported command, use **direct HTTP** to `POST {DTN_API_BASE}/api/command` with a valid body (same host as MCP).

---

## 8. MCP tools — full catalog

Unless stated, the return type is **`str`**: either pretty-printed JSON or CSV.

### 8.1 `dtn_get_api_base`

- **Description:** Return the resolved Mac API base URL (after env / `.env`).
- **Parameters:** none.
- **Backend:** none (config only).
- **Returns:** Plain string URL.

### 8.2 `dtn_get_config`

- **Description:** Safe configuration summary (no secrets). Confirms what the server loaded.
- **Parameters:** none.
- **Returns:** JSON string of `public_config_summary()` (see §4.1).

### 8.3 `dtn_get_status`

- **Description:** Latest Pi status (links, experiment mode, queue, emulation snapshot as provided by backend).
- **Parameters:** none.
- **Backend:** `GET /api/status`.
- **Errors:** On exception, returns JSON `{"ok": false, "error": "<message>"}` (does not raise to the client).

### 8.4 `dtn_get_telemetry_metrics`

- **Description:** Rolling window metrics: PDR, latency, deadline success/miss vs configured `deadline_ms`, etc.
- **Parameters:** none.
- **Backend:** `GET /api/metrics`.

### 8.5 `dtn_get_experiment_metrics`

- **Description:** Per-session experiment metrics (latency percentiles, delivery, duplicates, queue stats, etc.).
- **Parameters:** none.
- **Backend:** `GET /api/metrics/experiment`.

### 8.6 `dtn_get_experiment_distribution`

- **Description:** Grouped outcomes by experiment mode + emulation profile.
- **Parameters:** none.
- **Backend:** `GET /api/metrics/experiment/distribution`.

### 8.7 `dtn_set_experiment_mode`

- **Description:** Set Pi **experiment** mode; starts a new experiment session on the Pi.
- **Parameters:**
  - `mode` — `ExperimentMode` (required).
- **Backend:** `POST /api/command` with `{"cmd": "set_experiment_mode", "mode": "<mode>"}`.
- **Returns:** JSON string of the HTTP response body (typically `{"ok": true}`).

### 8.8 `dtn_set_emulation`

- **Description:** Apply netem-style emulation to WiFi, LTE, or both.
- **Parameters:**
  - `interface_role` — `InterfaceRole` (required).
  - `delay_ms` — int, default `0`.
  - `jitter_ms` — int, default `0`.
  - `loss_percent` — float, default `0.0`.
  - `bandwidth_kbps` — optional float, default `None` (omitted in JSON if unset).
  - `outage` — bool, default `false`.
- **Backend:** `POST /api/command` with `set_emulation` and nested `settings`.

### 8.9 `dtn_revert_emulation`

- **Description:** Remove emulation for the given interface role.
- **Parameters:**
  - `interface_role` — `InterfaceRole` (required).
- **Backend:** `POST /api/command` with `{"cmd": "revert_emulation", "interface_role": "..."}`.

### 8.10 `dtn_clear_queue`

- **Description:** Clear the Pi telemetry queue (management command).
- **Parameters:** none.
- **Backend:** `POST /api/command` with `{"cmd": "clear_queue"}`.

### 8.11 `dtn_set_link_manager_config`

- **Description:** Configure Pi link-manager timeout/scoring (`probe_timeout_s`, `rtt_ceil_ms`) and optionally restart the Pi agent. Values can persist to Pi `.env` per backend/Pi behavior. Use before long-delay profiles (e.g. Lunar/P-05 style scenarios).
- **Parameters:**
  - `probe_timeout_s` — optional float.
  - `rtt_ceil_ms` — optional float.
  - `restart_agent` — bool, default `true`.
- **Validation:** If **both** `probe_timeout_s` and `rtt_ceil_ms` are omitted, returns JSON error: `provide at least one of probe_timeout_s or rtt_ceil_ms` (no HTTP call).
- **Backend:** `POST /api/command` with `set_link_manager_config`.

### 8.12 `dtn_export_results_csv`

- **Description:** Export recent accepted telemetry results as **CSV** (suitable for Excel/Sheets).
- **Parameters:**
  - `limit` — optional int; default from `DTN_EXPORT_RESULTS_DEFAULT_LIMIT`; clamped to `DTN_EXPORT_RESULTS_MAX_LIMIT`.
- **Backend:** `GET /api/results?limit=<n>`.
- **Returns:** CSV string with header; empty list yields header-only for default columns (see implementation in `server.py`).

### 8.13 `dtn_run_timed_experiment`

- **Description:** Orchestration helper: set experiment mode, **sleep** warmup, **sleep** duration, then return combined metrics JSON. **Does not set emulation**—call `dtn_set_emulation` first if needed.
- **Parameters:**
  - `mode` — `ExperimentMode` (required).
  - `duration_seconds` — optional float; default `DTN_TIMED_DEFAULT_DURATION_SECONDS`.
  - `warmup_seconds` — optional float; default `DTN_TIMED_DEFAULT_WARMUP_SECONDS`.
- **Behavior:**
  1. `POST /api/command` `set_experiment_mode`.
  2. `time.sleep(max(0, warmup))`.
  3. `time.sleep(max(0, duration))`.
  4. Build JSON with keys: `mode`, `warmup_seconds`, `duration_seconds`, `telemetry_metrics`, `experiment_metrics` (from `GET /api/metrics` and `GET /api/metrics/experiment`).
- **Note:** This blocks the MCP server process for the full warmup+duration wall time.

---

## 9. Error handling pattern

For most tools, **exceptions are caught**, logged with `logger.exception`, and returned as JSON string `{"ok": false, "error": "..."}`.  
`dtn_export_results_csv` on failure returns a tiny CSV with an `error` column or `error\n'repr...'`.

The AI should **parse the return string** as JSON or CSV depending on the tool.

---

## 10. Security and operational warnings

- **`POST /api/command` forwards to the Pi** over the lab control plane. Treat `DTN_API_BASE` as **high privilege**: only run this MCP on trusted machines and networks.
- **Timed experiments** block the server for the sleep duration; long values can make the client appear hung.
- Mac API must be **reachable** before tools succeed (`curl`/`dtn_get_status` smoke test).

---

## 11. Related repo artifacts

- **Install / Claude Desktop / Inspector troubleshooting:** `dtn-mcp/README.md`.
- **Automation via MCP stdio:** `scripts/run_dtn_mcp_lunar_validation.py`, `scripts/run_dtn_mcp_repeats_report.py`, `scripts/run_dtn_mcp_exp2.py`, `scripts/run_dtn_mcp_exp3_5.py` (Python MCP client + stdio to the same server).

---

## 12. Quick checklist for an AI operating the testbed

1. Call **`dtn_get_config`** or **`dtn_get_api_base`** to verify URL and limits.
2. Call **`dtn_get_status`**; if error/503 path, ensure Mac stack and Pi connectivity.
3. Use **`dtn_set_link_manager_config`** if scenarios need extended timeouts before emulation.
4. Set **`dtn_set_emulation`** / **`dtn_set_experiment_mode`** as required; use **`dtn_revert_emulation`** when done.
5. Read **`dtn_get_telemetry_metrics`** / **`dtn_get_experiment_metrics`** / **`dtn_get_experiment_distribution`** for analysis.
6. Use **`dtn_export_results_csv`** for tabular export; **`dtn_run_timed_experiment`** for a fixed window sample (remember blocking).

This ends the MCP specification for the DTN Test Bed.
