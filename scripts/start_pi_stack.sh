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

load_env() {
  set -a
  # shellcheck disable=SC1090
  source "$1"
  set +a
}

bool_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

find_ud3tn() {
  if [[ -x "${REPO_ROOT}/third_party/ud3tn/build/posix/ud3tn" ]]; then
    echo "${REPO_ROOT}/third_party/ud3tn/build/posix/ud3tn"
    return
  fi

  if command -v ud3tn >/dev/null 2>&1; then
    command -v ud3tn
    return
  fi

  return 1
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

cleanup() {
  local code=$?
  if [[ -n "${UD3TN_PID:-}" ]] && kill -0 "${UD3TN_PID}" >/dev/null 2>&1; then
    kill "${UD3TN_PID}" >/dev/null 2>&1 || true
    wait "${UD3TN_PID}" 2>/dev/null || true
  fi
  if [[ -n "${UD3TN_PID_LTE:-}" ]] && kill -0 "${UD3TN_PID_LTE}" >/dev/null 2>&1; then
    kill "${UD3TN_PID_LTE}" >/dev/null 2>&1 || true
    wait "${UD3TN_PID_LTE}" 2>/dev/null || true
  fi
  exit "${code}"
}

start_ud3tn_instance() {
  local socket_path="$1"
  local aap2_socket="$2"
  local cla_port="$3"
  local log_file="$4"

  rm -f "${socket_path}" "${aap2_socket}"
  "${ud3tn_bin}" \
    --eid "${DTN_NODE_ID}" \
    --bp-version 7 \
    --aap-socket "${socket_path}" \
    --aap2-socket "${aap2_socket}" \
    --cla "mtcp:*,${cla_port}" \
    >"${log_file}" 2>&1 &

  local pid=$!
  sleep 2
  kill -0 "${pid}" >/dev/null 2>&1 || die "uD3TN exited early. See ${log_file}"
  echo "${pid}"
}

configure_contact() {
  local aap2_socket="$1"
  local log_file="$2"
  (
    cd "${REPO_ROOT}"
    PYTHONPATH="${REPO_ROOT}/third_party/ud3tn/python-ud3tn-utils${PYTHONPATH:+:${PYTHONPATH}}" \
    "${py_bin}" "${aap2_config_script}" \
      --socket "${aap2_socket}" \
      --schedule 1 "${contact_duration_s}" "${contact_bitrate_bps}" \
      "${DTN_DEST_NODE}" "mtcp:${MAC_DTN_IP}:${MAC_DTN_PORT}"
  ) >>"${log_file}" 2>&1 || {
    echo "---- $(basename "${log_file}") (last 40 lines) ----" >&2
    tail -n 40 "${log_file}" >&2 || true
    die "Failed to configure DTN contact. See ${log_file}"
  }
}

main() {
  local env_file="${REPO_ROOT}/pi-agent/.env"
  local agent_dir="${REPO_ROOT}/pi-agent"
  local dtn_port
  local aap2_socket
  local py_bin
  local contact_duration_s
  local contact_bitrate_bps
  local auto_config_contact
  local dtn_socket_wifi
  local dtn_socket_lte
  local aap2_socket_wifi
  local aap2_socket_lte
  local dtn_port_wifi
  local dtn_port_lte
  local start_lte_instance="false"

  [[ "$(uname -s)" == "Linux" ]] || die "start_pi_stack.sh must be run on Linux."
  [[ "${EUID}" -eq 0 ]] || die "Run start_pi_stack.sh with sudo on the Pi so link binding and netem controls work."
  need_file "${env_file}"
  need_file "${agent_dir}/main.py"
  need_file "${agent_dir}/.venv/bin/python"

  load_env "${env_file}"
  ud3tn_bin="$(find_ud3tn)" || die "uD3TN is not available. Run sudo bash scripts/setup_pi.sh first."
  dtn_port="${DTN_MTCP_PORT:-4224}"
  aap2_socket="${DTN_AAP2_SOCKET_PATH:-${REPO_ROOT}/ud3tn.aap2.socket}"
  py_bin="${agent_dir}/.venv/bin/python"
  contact_duration_s="${DTN_CONTACT_DURATION_S:-86400}"
  contact_bitrate_bps="${DTN_CONTACT_BITRATE_BPS:-100000}"
  auto_config_contact="${DTN_AUTO_CONFIG_CONTACT:-true}"
  dtn_socket_wifi="${DTN_SOCKET_PATH_WIFI:-${DTN_SOCKET_PATH}}"
  dtn_socket_lte="${DTN_SOCKET_PATH_LTE:-${DTN_SOCKET_PATH}}"
  aap2_socket_wifi="${DTN_AAP2_SOCKET_PATH_WIFI:-${aap2_socket}}"
  aap2_socket_lte="${DTN_AAP2_SOCKET_PATH_LTE:-${REPO_ROOT}/ud3tn-lte.aap2.socket}"
  dtn_port_wifi="${DTN_MTCP_PORT_WIFI:-${dtn_port}}"
  dtn_port_lte="${DTN_MTCP_PORT_LTE:-4225}"
  aap2_config_script="${REPO_ROOT}/third_party/ud3tn/python-ud3tn-utils/ud3tn_utils/aap2/bin/aap2_config.py"

  if [[ "${dtn_socket_lte}" != "${dtn_socket_wifi}" ]]; then
    start_lte_instance="true"
  fi

  if port_in_use "${dtn_port_wifi}"; then
    die "TCP port ${dtn_port_wifi} is already in use. Stop the existing uD3TN instance first."
  fi
  if bool_true "${start_lte_instance}" && port_in_use "${dtn_port_lte}"; then
    die "TCP port ${dtn_port_lte} is already in use. Stop the existing LTE-path uD3TN instance first."
  fi

  echo "==> Starting Pi uD3TN (default/WiFi path)"
  UD3TN_PID="$(start_ud3tn_instance "${dtn_socket_wifi}" "${aap2_socket_wifi}" "${dtn_port_wifi}" "${LOG_DIR}/pi-ud3tn.log")"

  if bool_true "${start_lte_instance}"; then
    echo "==> Starting Pi uD3TN (LTE redundant path)"
    UD3TN_PID_LTE="$(start_ud3tn_instance "${dtn_socket_lte}" "${aap2_socket_lte}" "${dtn_port_lte}" "${LOG_DIR}/pi-ud3tn-lte.log")"
  fi

  if bool_true "${auto_config_contact}"; then
    [[ -f "${aap2_config_script}" ]] || die "Missing uD3TN config tool: ${aap2_config_script}"
    [[ -x "${py_bin}" ]] || die "Missing Python interpreter: ${py_bin}"

    echo "==> Configuring DTN contact: ${DTN_DEST_NODE} via mtcp:${MAC_DTN_IP}:${MAC_DTN_PORT}"
    configure_contact "${aap2_socket_wifi}" "${LOG_DIR}/pi-ud3tn.log"
    if bool_true "${start_lte_instance}"; then
      configure_contact "${aap2_socket_lte}" "${LOG_DIR}/pi-ud3tn-lte.log"
    fi
  fi

  echo "==> Starting pi-agent"
  echo "    uD3TN log: ${LOG_DIR}/pi-ud3tn.log"
  if bool_true "${start_lte_instance}"; then
    echo "    LTE uD3TN log: ${LOG_DIR}/pi-ud3tn-lte.log"
  fi
  echo "    Press Ctrl-C to stop the Pi stack."
  (
    cd "${agent_dir}"
    ./.venv/bin/python main.py
  )
}

trap cleanup INT TERM EXIT
main "$@"
