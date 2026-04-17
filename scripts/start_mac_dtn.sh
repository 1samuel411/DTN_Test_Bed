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

load_env() {
  set -a
  # shellcheck disable=SC1090
  source "$1"
  set +a
}

cleanup() {
  local code=$?
  if [[ -n "${UD3TN_PID:-}" ]] && kill -0 "${UD3TN_PID}" >/dev/null 2>&1; then
    echo "==> Stopping uD3TN (pid ${UD3TN_PID})"
    kill "${UD3TN_PID}" >/dev/null 2>&1 || true
    wait "${UD3TN_PID}" 2>/dev/null || true
  fi
  exit "${code}"
}

main() {
  local env_file="${REPO_ROOT}/mac-backend/.env"

  local ud3tn_bin
  ud3tn_bin="$(command -v ud3tn 2>/dev/null || echo "${REPO_ROOT}/third_party/ud3tn/build/posix/ud3tn")"

  [[ "$(uname -s)" == "Darwin" ]] || die "start_mac_dtn.sh must be run on macOS."
  [[ -x "${ud3tn_bin}" ]] || die "ud3tn binary not found. Run scripts/setup_mac.sh first."
  need_file() { [[ -f "$1" ]] || die "Missing required file: $1"; }
  need_file "${env_file}"

  load_env "${env_file}"

  local eid="${DTN_NODE_ID:-dtn://mac-ground.dtn/}"
  local socket="${DTN_SOCKET_PATH:-/tmp/ud3tn.socket}"
  local mtcp_port="${DTN_MTCP_PORT:-4224}"

  # Remove stale socket if uD3TN is not already running
  if [[ -S "${socket}" ]]; then
    echo "==> Removing stale uD3TN socket: ${socket}"
    rm -f "${socket}"
  fi

  echo "==> Starting uD3TN"
  echo "    EID:       ${eid}"
  echo "    Socket:    ${socket}"
  echo "    MTCP port: ${mtcp_port}"
  echo "    Log:       ${LOG_DIR}/ud3tn-mac.log"

  "${ud3tn_bin}" \
    --eid "${eid}" \
    --bp-version 7 \
    --aap-socket "${socket}" \
    --cla "mtcp:0.0.0.0,${mtcp_port}" \
    >"${LOG_DIR}/ud3tn-mac.log" 2>&1 &
  UD3TN_PID=$!

  sleep 1
  kill -0 "${UD3TN_PID}" >/dev/null 2>&1 || die "uD3TN exited early. See ${LOG_DIR}/ud3tn-mac.log"

  echo "==> uD3TN running (pid ${UD3TN_PID}). Press Ctrl-C to stop."
  wait "${UD3TN_PID}"
}

trap cleanup INT TERM EXIT
main "$@"
