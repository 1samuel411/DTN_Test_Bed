# DTN Test Bed MCP (Claude Desktop)

This package exposes the Mac backend REST API to **Claude Desktop** via the [Model Context Protocol](https://modelcontextprotocol.io/) (stdio). Use it to change experiment modes, apply network emulation, read metrics, export **CSV** from recent results, and run simple timed experiment windows.

## Prerequisites

- Python **3.10+**
- Mac stack running with the HTTP API reachable (default in this repo: `http://<mac>:8080`). Same base URL as `VITE_API_URL` / `API_PORT` in `mac-backend`.

## 1. Install the MCP server

From the repository root:

```bash
cd dtn-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Confirm the module runs (it will wait for stdio; press Ctrl+C):

```bash
python -m dtn_mcp
```

You should see no output on **stdout** (MCP uses stdout for JSON-RPC). Logs go to **stderr**.

## 2. Configuration (`dtn-mcp/.env`)

All runtime settings are read from **`dtn-mcp/.env`**. Edit that file in the `dtn-mcp` directory (it is gitignored).

Set at least **`DTN_API_BASE`** to your Mac API URL (no trailing slash)—same host/port as `frontend/.env` (`VITE_API_URL`). Other keys in the file control HTTP timeouts, log level, CSV export limits, and timed-experiment defaults.

- Variables already set in the process environment (e.g. Claude Desktop `env` in `claude_desktop_config.json`) **override** `.env`.
- Optional: point at another file with **`DTN_MCP_ENV_PATH`** (absolute path to an env file).

Use tool **`dtn_get_config`** after connecting to confirm what the server loaded.

## Testing MCP functionality

### A. Confirm the Mac API first (no MCP)

If this fails, fix networking or `start_mac_stack.sh` before debugging MCP.

```bash
# Use the same DTN_API_BASE as in dtn-mcp/.env
export DTN_API_BASE="http://127.0.0.1:8080"   # or source .env: set -a; source .env; set +a
curl -sS "${DTN_API_BASE}/api/status" | head -c 400
curl -sS "${DTN_API_BASE}/api/metrics" | head -c 400
```

You want HTTP 200 and JSON, not connection refused.

### B. MCP Inspector (interactive tool calls)

Needs **Node.js** (`npx` on your `PATH`).

#### `mcp dev` and `uv` (common error)

`mcp dev` tells the Inspector to start your server with **`uv run …`**. If you see:

`Error: spawn uv ENOENT`

then **`uv` is not installed** (or not on `PATH`). Pick one:

**Option 1 — Install `uv` (simplest with `mcp dev`):**

```bash
brew install uv
# or: curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then:

```bash
cd dtn-mcp
source .venv/bin/activate
# Ensure .env exists (DTN_API_BASE, etc.); shell export not required
mcp dev dtn_mcp/server.py:mcp -e .
```

**Option 2 — No `uv`: use the Inspector with your venv `mcp` binary**

1. Start the Inspector only (still needs `npx`):

   ```bash
   cd dtn-mcp
   source .venv/bin/activate
   npx @modelcontextprotocol/inspector
   ```

2. When the UI opens, add or edit the **stdio** server connection and set:

   - **Command:** full path to the venv CLI, e.g.  
     `/Users/YOU/Documents/GitHub/DTN_Test_Bed/dtn-mcp/.venv/bin/mcp`
   - **Arguments:** `run` `dtn_mcp/server.py:mcp` (two args, or one string split per the UI)
   - **Working directory:** `dtn-mcp` project root (same folder as `pyproject.toml`)
   - **Environment:** optional if **`dtn-mcp/.env`** exists with `DTN_API_BASE` and other settings

3. Connect and run tools such as `dtn_get_status`.

#### Inspector: SSE errors on `localhost:3001`, or “nothing shows”

- **Ignore `localhost:3001/sse` / `ECONNREFUSED`:** the UI sometimes tries **SSE** or **Streamable HTTP** against a default URL where no server runs. Your DTN server uses **stdio** only. In the Inspector, set the connection type to **STDIO** (not SSE / HTTP). The log line `STDIO transport: command=.../uv` means the right path is active.
- **Shell `export` does not reach the server** when the Inspector spawns `uv` from the browser. Rely on **`dtn-mcp/.env`** for configuration (see §2). Restart the stdio connection after editing `.env`.
- **Seeing tools:** after STDIO connects, open the **Tools** (or **MCP** tools) panel, run **List Tools**, then invoke **`dtn_get_config`**, **`dtn_get_api_base`**, and **`dtn_get_status`**. If those fail, fix `.env` / Mac API (`curl` test above).

Claude Desktop does **not** use `uv`; it uses `python -m dtn_mcp` from your config, so this issue is Inspector-only.

### C. Claude Desktop

With `dtn-testbed` connected in Settings → Developer, start a chat and ask Claude to call **`dtn_get_status`** (read-only). If that works, try **`dtn_get_telemetry_metrics`** or **`dtn_export_results_csv`**.

### D. `mcp run` (stdio only)

Runs the server the same way Claude does (blocks on stdin). Useful to confirm it starts; you still need an MCP client on the other end of stdio.

```bash
mcp run dtn_mcp/server.py:mcp
```

Stop with Ctrl+C (exits quietly; the server catches `KeyboardInterrupt`).

## 3. Register the server in Claude Desktop (macOS)

1. Quit **Claude Desktop** completely (`Cmd+Q`).
2. Open (or create) the config file:

   `~/Library/Application Support/Claude/claude_desktop_config.json`

3. Merge a `mcpServers` entry. Adjust **paths** to match your machine (use the **absolute** path to this repo’s venv Python). With **`dtn-mcp/.env`** in place (§2), you do **not** need to duplicate `DTN_API_BASE` in Claude’s `env` unless you want an override.

### Option A: `python -m dtn_mcp` with venv

```json
{
  "mcpServers": {
    "dtn-testbed": {
      "command": "/Users/YOU/Documents/GitHub/DTN_Test_Bed/dtn-mcp/.venv/bin/python",
      "args": ["-m", "dtn_mcp"],
      "env": {}
    }
  }
}
```

Replace `YOU` with your user name. Add per-key overrides under `env` only if needed (they beat `.env`).

### Option B: `uv run` (if you use uv)

```json
{
  "mcpServers": {
    "dtn-testbed": {
      "command": "uv",
      "args": ["run", "--directory", "/Users/YOU/Documents/GitHub/DTN_Test_Bed/dtn-mcp", "python", "-m", "dtn_mcp"],
      "env": {}
    }
  }
}
```

4. Start **Claude Desktop** again.
5. Open **Settings → Developer** (or the MCP section, depending on app version) and confirm **dtn-testbed** is listed and connected.

If the server fails to start, check **Claude → Developer → logs** (or the MCP troubleshooting panel) for stderr from the Python process.

## 4. Using it in a chat

With the testbed online, you can ask Claude to:

- Set a mode: e.g. “Set experiment mode to `adaptive`.”
- Apply emulation, then run a timed window, then read metrics.
- Export data: “Call `dtn_export_results_csv` with limit 500 and give me the CSV.”

### Available tools (summary)

| Tool | Purpose |
|------|--------|
| `dtn_get_config` | Active settings (from `.env` / environment) |
| `dtn_get_api_base` | Mac API base URL only |
| `dtn_get_status` | Latest Pi status |
| `dtn_get_telemetry_metrics` | Rolling PDR, latency, deadline hit/miss |
| `dtn_get_experiment_metrics` | Session-scoped experiment metrics |
| `dtn_get_experiment_distribution` | Breakdown by mode/emulation |
| `dtn_set_experiment_mode` | `single_link_wifi` / `single_link_lte` / `adaptive` / `redundant` |
| `dtn_set_emulation` / `dtn_revert_emulation` | Netem profiles on WiFi/LTE/both |
| `dtn_clear_queue` | Clear Pi queue |
| `dtn_export_results_csv` | CSV of `/api/results` for spreadsheets |
| `dtn_run_timed_experiment` | Set mode, warmup, wait, return metrics JSON |

## 5. Optional: MCP Inspector

With the venv active and dependencies installed:

```bash
cd dtn-mcp
source .venv/bin/activate
mcp dev dtn_mcp/server.py
```

(Exact CLI flags depend on your `mcp` package version; see [python-sdk](https://github.com/modelcontextprotocol/python-sdk) docs.)

## Security note

`POST /api/command` forwards to your Pi. Only run this MCP on a trusted machine and network; treat `DTN_API_BASE` like root access to the lab control plane.
