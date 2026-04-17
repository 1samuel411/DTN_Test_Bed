#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="${REPO_ROOT}/.run"
LOG_DIR="${RUN_DIR}/logs"
mkdir -p "${LOG_DIR}"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

need_file() {
  [[ -f "$1" ]] || die "Missing required file: $1"
}

need_dir() {
  [[ -d "$1" ]] || die "Missing required directory: $1"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

load_env() {
  set -a
  # shellcheck disable=SC1090
  source "$1"
  set +a
}

port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
    return
  fi

  if command -v ss >/dev/null 2>&1; then
    ss -ltn "( sport = :${port} )" 2>/dev/null | grep -q ":${port}"
    return
  fi

  return 1
}

# Stop any process listening on the given TCP port so a fresh Mac stack can bind.
# Uses SIGTERM first, then SIGKILL if the port is still busy (macOS: lsof).
kill_tcp_listeners_on_port() {
  local port="$1"
  local pids
  local attempt

  port_in_use "${port}" || return 0

  if ! command -v lsof >/dev/null 2>&1; then
    die "TCP port ${port} is in use and lsof is not available to stop the listener."
  fi

  for attempt in 1 2; do
    pids="$(lsof -nP -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null | sort -u | tr '\n' ' ')"
    pids="${pids%% }"
    [[ -z "${pids}" ]] && break

    if [[ "${attempt}" -eq 1 ]]; then
      echo "==> Stopping listener(s) on port ${port} (PID(s): ${pids})"
      # shellcheck disable=SC2086
      kill ${pids} 2>/dev/null || true
    else
      echo "==> Force-stopping listener(s) on port ${port} (PID(s): ${pids})"
      # shellcheck disable=SC2086
      kill -9 ${pids} 2>/dev/null || true
    fi

    sleep 0.4
    port_in_use "${port}" || return 0
  done

  port_in_use "${port}" && die "Could not free TCP port ${port}. Stop the process using it and retry."
}

clear_other_stack_servers() {
  local frontend_dev_port="${FRONTEND_DEV_PORT:-5173}"

  echo "==> Clearing listeners for Mac stack ports (${API_PORT}, ${CONFIG_PORT}, Vite ${frontend_dev_port})"
  kill_tcp_listeners_on_port "${API_PORT}"
  kill_tcp_listeners_on_port "${CONFIG_PORT}"
  kill_tcp_listeners_on_port "${frontend_dev_port}"
}

cleanup() {
  local code=$?
  if [[ -n "${APP_PID:-}" ]] && kill -0 "${APP_PID}" >/dev/null 2>&1; then
    kill "${APP_PID}" >/dev/null 2>&1 || true
    wait "${APP_PID}" 2>/dev/null || true
  fi
  exit "${code}"
}

main() {
  local env_file="${REPO_ROOT}/mac-backend/.env"
  local backend_dir="${REPO_ROOT}/mac-backend"
  local frontend_dir="${REPO_ROOT}/frontend"
  local frontend_host

  [[ "$(uname -s)" == "Darwin" ]] || die "start_mac_stack.sh must be run on macOS."
  need_file "${env_file}"
  need_file "${backend_dir}/main.py"
  need_dir "${frontend_dir}/node_modules"
  need_file "${backend_dir}/.venv/bin/python"
  need_cmd npm

  load_env "${env_file}"
  frontend_host="${FRONTEND_PUBLIC_HOST:-${CONFIG_HOST}}"

  clear_other_stack_servers

  echo "==> Starting Mac backend (API + Config Server)"
  (
    cd "${backend_dir}"
    export ENABLE_DTN_BRIDGE="${ENABLE_DTN_BRIDGE:-false}"
    exec ./.venv/bin/python main.py
  ) >"${LOG_DIR}/mac-backend.log" 2>&1 &
  APP_PID=$!
  sleep 2
  kill -0 "${APP_PID}" >/dev/null 2>&1 || die "Mac backend exited early. See ${LOG_DIR}/mac-backend.log"

  echo "==> Starting frontend"
  echo "    Backend log: ${LOG_DIR}/mac-backend.log"
  echo "    Frontend API URL: http://${frontend_host}:${API_PORT}"
  echo "    Frontend WS URL:  ws://${frontend_host}:${API_PORT}"
  echo "    Launching Vite dev server"
  echo "    Press Ctrl-C to stop the Mac frontend/backend stack."
  (
    cd "${frontend_dir}"
    export VITE_API_URL="${VITE_API_URL:-http://${frontend_host}:${API_PORT}}"
    export VITE_WS_URL="${VITE_WS_URL:-ws://${frontend_host}:${API_PORT}}"
    npm run dev
  )
}

trap cleanup INT TERM EXIT
main "$@"
