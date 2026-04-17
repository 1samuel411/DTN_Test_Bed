# DTN Test Bed — Architecture

This document describes what lives in the repo and how the pieces fit together at runtime. It is the "box-and-arrow" companion to [setup.md](setup.md) (host/network configuration) and [MCP.md](MCP.md) (AI / automation control surface).

## 1. What this testbed is

A two-node, two-link **Delay-Tolerant Networking (DTN)** test bed built around the [µD3TN](https://gitlab.com/d3tn/ud3tn) bundle protocol agent. A **Raspberry Pi** ("Pi") acts as the mobile sender; a **Mac** acts as the ground station and control plane. Two separate IP paths — **WiFi** and **LTE** (tethered or USB modem) — carry DTN traffic in parallel; a management **Ethernet** link carries control-plane traffic only.

The testbed supports four experiment modes:

- `single_link_wifi` — force all DTN traffic over WiFi
- `single_link_lte` — force all DTN traffic over LTE
- `adaptive` — score WiFi and LTE with an EWMA of RTT + availability and switch with hysteresis/hold-time
- `redundant` — send every bundle on both links, deduplicate on the Mac

On top of DTN, a telemetry pipeline measures **latency**, **Packet Delivery Ratio (PDR)**, **deadline-miss rate** (against `REALTIME_DEADLINE_MS`), **duplicates**, **queue depth**, and **switchover events**. A React frontend renders live metrics; an MCP server exposes the whole thing to AI assistants.

## 2. Repository layout

```
DTN_Test_Bed/
├── mac-backend/          Python backend that runs on the Mac
│   ├── main.py               Entry point: boots all three services
│   ├── config.py             Env-driven settings
│   ├── api_server/           FastAPI REST + /ws WebSocket on :8080
│   ├── config_server/        WebSocket management endpoint on :8765
│   ├── dtn_receiver_bridge/  Pulls bundles off the local uD3TN AAP socket
│   └── shared/               Pydantic schemas + shared Store (SQLite-backed)
│
├── pi-agent/             Python agent that runs on the Pi
│   ├── main.py               Entry point: composes all services
│   ├── config.py             Env-driven settings
│   ├── gps_reader/           NMEA serial → telemetry events
│   ├── queue_manager/        Bounded FIFO GPS → DTN sender
│   ├── dtn_sender/           Pulls from queue, hands bundles to uD3TN over AAPv1
│   ├── link_manager/         Probes WiFi/LTE, picks active link, emits events
│   ├── netem_agent/          Applies/reverts tc-netem profiles locally
│   ├── mgmt_client/          WebSocket client → Mac config_server
│   ├── schemas.py            Pydantic wire schemas (shared shape with Mac)
│   └── systemd/              Unit files for pi-agent + ud3tn on the Pi
│
├── frontend/             React + Vite dashboard (served on the Mac)
│   └── src/{api,app,components,features,hooks,lib,types,styles}
│
├── dtn-mcp/              Standalone MCP (stdio) server — AI control surface
│   ├── dtn_mcp/server.py     FastMCP tool definitions
│   ├── dtn_mcp/config.py     DTN_API_BASE, timeouts, limits
│   └── README.md             Install + Claude Desktop registration guide
│
├── scripts/              Setup, start, and experiment orchestration
│   ├── setup_mac.sh / setup_pi.sh
│   ├── start_mac_stack.sh / start_mac_dtn.sh / start_pi_stack.sh
│   ├── build_final_output_workbook.py / export_dtn_workbook_charts.py
│   ├── run_dtn_targeted_repair_validation.py
│   └── sd-first-boot/             First-boot provisioning for a Pi SD image
│
├── third_party/ud3tn/    µD3TN source (submodule-style vendor checkout, gitignored)
├── artifacts/            Experiment run outputs (JSON checkpoints, validation)
├── .run/                 Local runtime (SQLite DB + logs; gitignored)
├── docs/                 This folder — architecture, setup, MCP reference
├── DTN_Experiment_Results.xlsx, experiment_results.json
│                         Canonical results workbook and raw JSON
├── populate_sheets.gs    Google Apps Script that mirrors results into Sheets
└── README.md             Top-level orientation
```

## 3. Runtime topology

There are two machines, three IP planes, and (in redundant mode) two DTN sockets.

```
                       ┌────────────────────────────────────────────────┐
                       │                      Mac                       │
  WiFi  ────DTN:4224──▶│  uD3TN  ──AAPv1──▶  dtn_receiver_bridge ──┐    │
                       │                                           ▼    │
  LTE   ────DTN:4224──▶│                                     shared.Store│
                       │                                           ▲    │
                       │                                           │    │
  Ethernet ─mgmt:8765─▶│  config_server  ◀── WebSocket ───────────┤    │
                       │                                           │    │
                       │  api_server  :8080  (REST + /ws)  ────────┘    │
                       └────────────────────────────────────────────────┘
                                 ▲                          ▲
                                 │ HTTP                     │ WebSocket /ws
                                 │                          │
                         dtn-mcp (stdio)               frontend (Vite)
                                 ▲
                                 │ JSON-RPC over stdio
                                 │
                     Claude Desktop / Cursor / MCP Inspector
```

**Pi side**, in parallel:

```
GPSReader ─▶ QueueManager ─▶ DTNSender ──AAPv1──▶ uD3TN ──IP──▶ Mac
                                 ▲
LinkManager ─── probes WiFi/LTE, sets active link, emits events
NetemAgent  ── applies tc-netem profiles when asked over mgmt_client
MgmtClient  ── WebSocket to Mac config_server (status push, commands)
```

Three IP planes, none of them overlap:

| Plane | Mac | Pi | Purpose |
|-------|-----|----|---------|
| Management (Ethernet) | `10.0.0.1:8765` | `10.0.0.2` | Commands, status push, config |
| DTN data (WiFi/LTE) | `192.168.1.100:4224` | any reachable | Bundles — the thing under test |
| Frontend HTTP/WS | `10.0.0.1:8080` | n/a | Dashboard + MCP control |

## 4. Component responsibilities

### 4.1 Mac backend (`mac-backend/`)

Boots from [`mac-backend/main.py`](../mac-backend/main.py) and runs three cooperating services against one shared `Store`:

- **`config_server`** (WebSocket, `10.0.0.1:8765`) — accepts the Pi's management connection, pushes commands to it, ingests status reports.
- **`api_server`** (FastAPI + WebSocket, `0.0.0.0:8080`) — REST API for the frontend and for `dtn-mcp`; `/ws` for live updates. Exposes `/api/status`, `/api/telemetry`, `/api/results`, `/api/events`, `/api/metrics`, `/api/metrics/experiment`, `/api/metrics/experiment/distribution`, `/api/dtn/counters`, `/api/experiment-recording-runs`, and `POST /api/command` (forwarded to the Pi via `config_server`).
- **`dtn_receiver_bridge`** (AAPv1 client against the local uD3TN socket) — reads delivered bundles and writes telemetry rows into `Store`. Toggled by `ENABLE_DTN_BRIDGE`.

`shared/store.py` is the single source of truth for telemetry, events, and derived metrics; it is SQLite-backed at `.run/dtn_testbed.db` by default.

### 4.2 Pi agent (`pi-agent/`)

Boots from [`pi-agent/main.py`](../pi-agent/main.py). Services:

- **`gps_reader`** — opens a u-blox / NMEA serial port (or `auto`-detects), parses fixes at `GPS_READ_INTERVAL_S`, throttles outbound to `GPS_SEND_FREQUENCY_HZ`, emits `PiStatusReport` + telemetry rows.
- **`queue_manager`** — bounded FIFO (`MAX_QUEUE_SIZE`) between producer (GPS) and consumer (DTN). Tracks queue depth per-sample.
- **`dtn_sender`** — hands each telemetry bundle to uD3TN via AAPv1 (`dtn_adapter.py`). In **redundant** mode it uses two separate uD3TN sockets (`DTN_SOCKET_PATH_WIFI` and `DTN_SOCKET_PATH_LTE`).
- **`link_manager`** — periodic WiFi/LTE probes; rolling availability + EWMA-smoothed RTT; scores each link (`W_RTT`, `W_AVAIL`); switches only when the challenger beats the incumbent by `SCORE_HYSTERESIS` for `ADAPTIVE_WIN_STREAK` probes, and no more often than `HOLD_TIME_S`. Immediate failover after `IMMEDIATE_FAILOVER_FAILURES` hard failures.
- **`netem_agent`** — applies or reverts `tc netem` (delay / jitter / loss / bandwidth / outage) per interface role (`wifi` / `lte` / `both`).
- **`mgmt_client`** — WebSocket client to the Mac. Receives `set_experiment_mode`, `set_emulation`, `revert_emulation`, `clear_queue`, `set_link_manager_config`, `set_mode`, `set_baudrate`, `set_gps_send_frequency`. Pushes `PiStatusReport` on a cadence.

### 4.3 Frontend (`frontend/`)

React + Vite SPA. Reads `VITE_API_URL` / `VITE_WS_URL` to reach the Mac API. Shows the live experiment mode, active link and per-link scores, GPS + interface status, DTN sent/received counters, latency and queue-wait, unique delivery rate, real-time deadline success, and duplicate/switchover events.

### 4.4 DTN MCP server (`dtn-mcp/`)

Standalone Python package — not started by the Mac stack scripts. Talks **stdio JSON-RPC** to an MCP client (Claude Desktop, Cursor, MCP Inspector) and **HTTP** to the Mac API. It is a remote-control façade; it does not implement DTN logic. Full tool catalog and env vars in [MCP.md](MCP.md). Install / register in Claude Desktop via [`dtn-mcp/README.md`](../dtn-mcp/README.md).

### 4.5 Scripts (`scripts/`)

- **`setup_mac.sh` / `setup_pi.sh`** — idempotent bootstrappers: validate `.env`, install OS deps, build venvs, install Python + (on Mac) npm deps, build or locate `third_party/ud3tn`.
- **`start_mac_stack.sh`** — boots `mac-backend` + Vite frontend with logs under `.run/logs/`.
- **`start_mac_dtn.sh`** — starts the Mac-side uD3TN instance used by `dtn_receiver_bridge`.
- **`start_pi_stack.sh`** — boots Pi uD3TN (once, or twice for redundant mode) + `pi-agent`.
- **`run_dtn_targeted_repair_validation.py`** and the other `run_dtn_mcp_*` orchestrators — drive the MCP stdio server programmatically to run scripted campaigns (set emulation → set mode → wait → read metrics → checkpoint JSON under `artifacts/`).
- **`build_final_output_workbook.py`, `export_dtn_workbook_charts.py`** — build `DTN_Experiment_Results.xlsx` from `experiment_results.json`.
- **`sd-first-boot/`** — one-shot provisioning scripts embedded in a Pi SD image.

## 5. Data paths at a glance

| Event | Path |
|-------|------|
| GPS fix → delivered bundle | `gps_reader` → `queue_manager` → `dtn_sender` → Pi uD3TN → IP (WiFi/LTE) → Mac uD3TN → `dtn_receiver_bridge` → `Store` |
| Command (set mode etc.) | MCP tool / frontend / curl → `api_server POST /api/command` → `config_server.send_command` → Pi `mgmt_client` → relevant Pi service |
| Pi status push | `PiStatusReport` → `mgmt_client` → `config_server` → `Store` → `api_server` broadcast → frontend `/ws` |
| Metrics read | `Store` derives → `api_server GET /api/metrics[/experiment[/distribution]]` → MCP tool / frontend |

## 6. Persistence and artifacts

- **`.run/dtn_testbed.db`** — SQLite; the Store's backing file. Gitignored.
- **`.run/logs/`** — stdout/stderr of `start_mac_stack.sh` and `start_pi_stack.sh`. Gitignored.
- **`artifacts/`** — JSON checkpoints from MCP-driven campaigns (e.g. `dtn_targeted_repair_validation_*.json`). Checked in.
- **`experiment_results.json`** + **`DTN_Experiment_Results.xlsx`** — canonical results, updated by `build_final_output_workbook.py`.
- **`populate_sheets.gs`** — Google Apps Script that mirrors the JSON/XLSX into a shared Google Sheet.

## 7. Further reading

- [docs/setup.md](setup.md) — concrete host/network configuration, setup + start scripts, and the experiment sequence.
- [docs/MCP.md](MCP.md) — the full MCP server specification: environment, HTTP mapping, every tool.
- [dtn-mcp/README.md](../dtn-mcp/README.md) — installing `dtn-mcp` and registering it with Claude Desktop.
- [µD3TN docs](https://gitlab.com/d3tn/ud3tn) — upstream bundle protocol agent used in `third_party/ud3tn`.
