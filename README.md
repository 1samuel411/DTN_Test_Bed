# DTN Test Bed

A two-node **Delay-Tolerant Networking** test bed built around [µD3TN](https://gitlab.com/d3tn/ud3tn). A Raspberry Pi streams GPS telemetry over two parallel IP links — **WiFi** and **LTE** — to a Mac ground station. The Mac runs the DTN receiver, a live metrics API and React dashboard, and an MCP server that lets an AI assistant (Claude Desktop, Cursor, the MCP Inspector) drive experiments end-to-end.

Four experiment modes are supported:

- `single_link_wifi` — WiFi only
- `single_link_lte` — LTE only
- `adaptive` — EWMA-scored link selection with hysteresis and hold-time
- `redundant` — send every bundle on both links, deduplicate on receipt

Metrics collected per session: latency distribution, Packet Delivery Ratio, real-time deadline miss rate (against `REALTIME_DEADLINE_MS`), duplicates, queue depth, and switchover events.

## Repository layout

```
DTN_Test_Bed/
├── mac-backend/      Python backend (FastAPI + config WebSocket + uD3TN bridge)
├── pi-agent/         Python agent (GPS, queue, DTN sender, link manager, netem)
├── frontend/         React + Vite dashboard served from the Mac
├── dtn-mcp/          MCP (stdio) server exposing the Mac API to AI clients
├── scripts/          setup_*, start_*, experiment orchestrators, workbook builders
├── third_party/ud3tn µD3TN source (vendor checkout; gitignored)
├── artifacts/        JSON checkpoints from MCP-driven campaigns
├── docs/             architecture.md, setup.md, MCP.md
├── DTN_Experiment_Results.xlsx, experiment_results.json   Canonical results
└── populate_sheets.gs                                      Google Sheets mirror
```

## Quick start

See **[docs/setup.md](docs/setup.md)** for the full walkthrough. The short version, once the three `.env` files match your network:

```bash
# Mac
bash scripts/setup_mac.sh
bash scripts/start_mac_stack.sh   # backend :8080, config :8765, frontend via Vite
bash scripts/start_mac_dtn.sh     # Mac-side uD3TN receiver

# Pi
sudo bash scripts/setup_pi.sh
sudo bash scripts/start_pi_stack.sh   # Pi uD3TN (x1 or x2) + pi-agent
```

Smoke-test the Mac API from any host on the management LAN:

```bash
curl -sS http://10.0.0.1:8080/api/status  | head -c 400
curl -sS http://10.0.0.1:8080/api/metrics | head -c 400
```

Change experiment mode with a single HTTP call (or through the dashboard, or via MCP):

```bash
curl -sS -X POST http://10.0.0.1:8080/api/command \
  -H 'content-type: application/json' \
  -d '{"cmd":"set_experiment_mode","mode":"adaptive"}'
```

## Driving experiments with an AI assistant

The `dtn-mcp` package is a stdio MCP server that proxies the Mac REST API. Register it with Claude Desktop once, and an AI client can set modes, apply netem profiles, run timed windows, and export CSV results.

- Install and register: **[dtn-mcp/README.md](dtn-mcp/README.md)**
- Full tool catalog, env vars, HTTP mapping, and error semantics: **[docs/MCP.md](docs/MCP.md)**

`scripts/run_dtn_*` are Python orchestrators that speak to the same MCP server programmatically and checkpoint JSON to `artifacts/`.

## Documentation

- [docs/architecture.md](docs/architecture.md) — components, runtime topology, data paths
- [docs/setup.md](docs/setup.md) — network config, setup/start scripts, running experiments, troubleshooting
- [docs/MCP.md](docs/MCP.md) — MCP server specification and tool reference
- [dtn-mcp/README.md](dtn-mcp/README.md) — installing the MCP server and registering it with Claude Desktop

## Results

`experiment_results.json` is the raw output; `DTN_Experiment_Results.xlsx` is the rendered workbook (rebuild with `scripts/build_final_output_workbook.py` + `scripts/export_dtn_workbook_charts.py`). `populate_sheets.gs` mirrors the same data into a shared Google Sheet.

## Security note

`POST /api/command` on the Mac backend forwards directly to the Pi control plane, and `dtn-mcp` is a thin shim over that endpoint. Treat `DTN_API_BASE` and the Mac management IP as high-privilege — only run the stack on trusted machines and networks.
