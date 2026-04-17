# DTN Testbed Setup

This document takes a freshly cloned repo to a running testbed. For a higher-level tour of what the components are and how they fit together, see [architecture.md](architecture.md); for the AI control surface, see [MCP.md](MCP.md).

This repo is configured around three tracked `.env` files:

- [mac-backend/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/mac-backend/.env)
- [pi-agent/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/pi-agent/.env)
- [frontend/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/frontend/.env)

The current checked-in values imply this network layout:

- Mac Ethernet / control plane: `10.0.0.1`
- Pi Ethernet / control plane: `10.0.0.2`
- Mac DTN data-plane IP: `192.168.1.100`
- Frontend API/WS target: `10.0.0.1:8080`

For class demos, the intended experiment sequence is:

- `single_link_wifi`
- `single_link_lte`
- `adaptive`
- `redundant`

## 1. Review the current config

### Mac
In [mac-backend/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/mac-backend/.env):

- `CONFIG_HOST=10.0.0.1`
- `CONFIG_PORT=8765`
- `API_PORT=8080`
- `FRONTEND_PUBLIC_HOST=10.0.0.1`
- `REALTIME_DEADLINE_MS=2000`
- `METRICS_WINDOW_SIZE=100`

What that means:

- The Mac backend listens for Pi management traffic on `10.0.0.1:8765`
- The frontend expects the API on `http://10.0.0.1:8080`
- Real-time deadline success is measured against a `2000 ms` deadline
- Rolling metrics (PDR, latency, deadline miss rate) are computed over the most recent `100` samples

### Pi
In [pi-agent/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/pi-agent/.env):

- `MAC_DTN_IP=192.168.1.100`
- `MGMT_SERVER_IP=10.0.0.1`
- `ETH_STATIC_IP=10.0.0.2`
- `DEFAULT_LINK_MODE=auto`
- `CONNECTIVITY_CHECK_S=1`
- `FAILOVER_THRESHOLD=3`
- `DTN_SOCKET_PATH_WIFI=/tmp/ud3tn.socket`
- `DTN_SOCKET_PATH_LTE=/tmp/ud3tn-lte.socket`

What that means:

- The Pi sends DTN traffic toward the Mac at `192.168.1.100:4224`
- The Pi management client connects to the Mac over Ethernet at `10.0.0.1:8765`
- The Pi expects its management-side Ethernet address to be `10.0.0.2`
- Adaptive link selection probes every `1` second and switches only after score hysteresis and hold time
- If `DTN_SOCKET_PATH_WIFI` and `DTN_SOCKET_PATH_LTE` differ, `start_pi_stack.sh` launches two Pi-side uD3TN sender sockets for redundant-mode experiments

### Frontend
In [frontend/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/frontend/.env):

- `VITE_API_URL=http://10.0.0.1:8080`
- `VITE_WS_URL=ws://10.0.0.1:8080`

That means the React web frontend is currently configured to talk to the Mac at `10.0.0.1`.

If your phone cannot reach `10.0.0.1`, update both:

- `FRONTEND_PUBLIC_HOST` in [mac-backend/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/mac-backend/.env)
- `VITE_API_URL` and `VITE_WS_URL` in [frontend/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/frontend/.env)

## 2. Mac setup

Run from the repo root on the Mac:

```bash
bash scripts/setup_mac.sh
```

This script:

- validates [mac-backend/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/mac-backend/.env)
- installs required Mac packages
- creates `mac-backend/.venv`
- installs backend Python dependencies
- installs frontend npm dependencies
- builds or locates `uD3TN`

Before starting, make sure the Mac Ethernet interface is actually configured as `10.0.0.1`.

## 3. Pi setup

Run from the repo root on the Pi:

```bash
sudo bash scripts/setup_pi.sh
```

This script:

- validates [pi-agent/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/pi-agent/.env)
- installs Linux dependencies
- creates `pi-agent/.venv`
- installs Python dependencies
- builds or locates `uD3TN`

Before starting, make sure:

- the Pi can reach the Mac management interface at `10.0.0.1`
- `MAC_DTN_IP=192.168.1.100` is correct for your Mac's WiFi/LTE-reachable interface

`pi-agent/systemd/pi-agent.service` and `pi-agent/systemd/ud3tn-pi.service` are available if you want the stack to come up on boot instead of via `start_pi_stack.sh`.

## 4. Start the stacks

### Mac

```bash
bash scripts/start_mac_stack.sh
```

This starts:

- Mac backend on `0.0.0.0:8080`
- Config server on `10.0.0.1:8765`
- React web frontend via Vite

Logs land under `.run/logs/`. The script does **not** start the Mac-side uD3TN or the Pi stack — those are separate.

If you need the Mac-side uD3TN receiver (required for `dtn_receiver_bridge` to actually see bundles), run:

```bash
bash scripts/start_mac_dtn.sh
```

### Pi

```bash
sudo bash scripts/start_pi_stack.sh
```

This starts:

- Pi uD3TN on `0.0.0.0:4224`
- Optional second Pi uD3TN instance on `0.0.0.0:4225` when `DTN_SOCKET_PATH_LTE` differs from `DTN_SOCKET_PATH_WIFI`
- Pi agent

## 5. What you should see

Once both sides are running, the `DTN Testbed` frontend should show:

- current experiment mode
- active link and per-link health/score
- interface and GPS status
- DTN sent/received counters
- latency and queue wait
- unique delivery rate
- real-time deadline success
- duplicate and switchover events

A quick sanity check from any machine that can reach the Mac API:

```bash
curl -sS http://10.0.0.1:8080/api/status   | head -c 400
curl -sS http://10.0.0.1:8080/api/metrics  | head -c 400
```

Both should return HTTP 200 and JSON (not connection refused, not 503 with `"no status yet"` beyond the first few seconds).

## 6. Running experiments

Three interfaces drive experiments. Pick whichever fits the situation.

### 6.1 Frontend controls

The React dashboard has buttons to change experiment mode and toggle emulation profiles. This is the easiest path for demos.

### 6.2 Direct HTTP

Every control is just a `POST /api/command` away:

```bash
# Set experiment mode
curl -sS -X POST http://10.0.0.1:8080/api/command \
  -H 'content-type: application/json' \
  -d '{"cmd":"set_experiment_mode","mode":"adaptive"}'

# Apply 300 ms delay + 1% loss to WiFi
curl -sS -X POST http://10.0.0.1:8080/api/command \
  -H 'content-type: application/json' \
  -d '{"cmd":"set_emulation","interface_role":"wifi",
       "settings":{"delay_ms":300,"jitter_ms":20,"loss_percent":1.0}}'

# Revert WiFi emulation
curl -sS -X POST http://10.0.0.1:8080/api/command \
  -H 'content-type: application/json' \
  -d '{"cmd":"revert_emulation","interface_role":"wifi"}'
```

### 6.3 MCP (Claude Desktop / Cursor / Inspector)

Install and register `dtn-mcp` once per machine (see [dtn-mcp/README.md](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/dtn-mcp/README.md)), point `DTN_API_BASE` at the Mac, and an AI client can drive the full flow. Tool reference: [MCP.md](MCP.md).

### 6.4 Scripted campaigns

The `scripts/` folder contains a few Python orchestrators that drive `dtn-mcp` over stdio and checkpoint JSON to `artifacts/`:

- [scripts/run_dtn_targeted_repair_validation.py](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/scripts/run_dtn_targeted_repair_validation.py) — targeted repair validation run
- [scripts/build_final_output_workbook.py](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/scripts/build_final_output_workbook.py) / [scripts/export_dtn_workbook_charts.py](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/scripts/export_dtn_workbook_charts.py) — rebuild `DTN_Experiment_Results.xlsx` from `experiment_results.json`
- [populate_sheets.gs](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/populate_sheets.gs) — Google Apps Script that mirrors results into a Google Sheet

Run these from the repo root with the Mac stack already up.

## 7. Troubleshooting

- **Mac API returns 503 `"no status yet"`** — the Pi hasn't connected to `config_server` on `10.0.0.1:8765` yet. Check that Ethernet is cabled, `ETH_STATIC_IP=10.0.0.2` is applied on the Pi, and `MGMT_SERVER_IP=10.0.0.1` is reachable (`ping 10.0.0.1` from the Pi).
- **Mac API not reachable at all** — `start_mac_stack.sh` hasn't been run, or the port is blocked. Logs are in `.run/logs/`.
- **No bundles land on the Mac** — uD3TN isn't running on one side. Confirm Pi uD3TN is listening on `:4224` (and `:4225` if redundant), and that `start_mac_dtn.sh` is running on the Mac.
- **Adaptive mode never switches** — check `PROBE_TIMEOUT_S`, `SCORE_HYSTERESIS`, `HOLD_TIME_S` in [pi-agent/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/pi-agent/.env). Long-delay scenarios (e.g. Lunar / P-05) usually need a higher `PROBE_TIMEOUT_S` and `RTT_CEIL_MS`; the `dtn_set_link_manager_config` MCP tool can patch these without editing the file.
- **MCP tools time out** — `DTN_HTTP_TIMEOUT_SECONDS` is too low for `dtn_run_timed_experiment` with a long duration. Bump it in `dtn-mcp/.env`.

## 8. Most likely changes you will need

If you are using the repo exactly as checked in, the most likely value you must change is:

- `MAC_DTN_IP` in [pi-agent/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/pi-agent/.env)

You may also need to change:

- `FRONTEND_PUBLIC_HOST` in [mac-backend/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/mac-backend/.env)
- `VITE_API_URL` in [frontend/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/frontend/.env)
- `VITE_WS_URL` in [frontend/.env](/Users/samarminana/Documents/GitHub/DTN_Test_Bed/frontend/.env)
