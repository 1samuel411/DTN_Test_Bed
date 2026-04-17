#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PI_ENV="${REPO_ROOT}/pi-agent/.env"
PI_DIR="${REPO_ROOT}/pi-agent"
UD3TN_DIR="${REPO_ROOT}/third_party/ud3tn"
UD3TN_BIN="${UD3TN_DIR}/build/posix/ud3tn"

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

check_config() {
  need_file "${PI_ENV}"
  load_env "${PI_ENV}"

  local required=(
    DTN_NODE_ID
    DTN_DEST_NODE
    DTN_SOCKET_PATH
    MAC_DTN_IP
    MAC_DTN_PORT
    MGMT_SERVER_IP
    MGMT_SERVER_PORT
  )

  for key in "${required[@]}"; do
    [[ -n "${!key:-}" ]] || die "pi-agent/.env is missing ${key}"
  done

  [[ "${MAC_DTN_IP}" != "192.168.1.100" ]] || die "Set MAC_DTN_IP in pi-agent/.env to the Mac's real WiFi/LTE-reachable address before setup."
}

install_apt_deps() {
  apt-get update -y
  apt-get install -y \
    python3 python3-venv python3-pip \
    iproute2 iputils-ping lsof \
    git build-essential cmake ninja-build pkg-config

  modprobe sch_netem >/dev/null 2>&1 || echo "WARNING: sch_netem module not available yet; netem controls may fail until it is installed."
}

build_ud3tn_if_needed() {
  if command -v ud3tn >/dev/null 2>&1; then
    echo "Using system ud3tn: $(command -v ud3tn)"
    return
  fi

  if [[ ! -x "${UD3TN_BIN}" ]]; then
    mkdir -p "$(dirname "${UD3TN_DIR}")"
    if [[ ! -d "${UD3TN_DIR}" ]]; then
      git clone https://gitlab.com/d3tn/ud3tn.git "${UD3TN_DIR}"
    fi
    (
      cd "${UD3TN_DIR}" && \
      git submodule sync --recursive && \
      git submodule update --init --recursive && \
      make -j"$(nproc)" ud3tn
    )
  fi

  [[ -x "${UD3TN_BIN}" ]] || die "uD3TN build failed. Expected binary at ${UD3TN_BIN}"
}

setup_agent() {
  local pyd3tn_dir="${UD3TN_DIR}/pyd3tn"
  local ud3tn_utils_dir="${UD3TN_DIR}/python-ud3tn-utils"

  python3 -m venv "${PI_DIR}/.venv"
  "${PI_DIR}/.venv/bin/pip" install --upgrade pip
  "${PI_DIR}/.venv/bin/pip" install -r "${PI_DIR}/requirements.txt"

  # Install local sources to avoid resolver conflicts from stale wheel metadata.
  if [[ -d "${pyd3tn_dir}" ]] && [[ -d "${ud3tn_utils_dir}" ]]; then
    "${PI_DIR}/.venv/bin/pip" install "${pyd3tn_dir}" "${ud3tn_utils_dir}"
  fi
}

main() {
  [[ "$(uname -s)" == "Linux" ]] || die "setup_pi.sh must be run on Linux"
  [[ "${EUID}" -eq 0 ]] || die "Run setup_pi.sh with sudo so apt and netem dependencies can be installed."

  echo "==> Checking Pi configuration"
  check_config

  echo "==> Installing Pi dependencies"
  install_apt_deps

  echo "==> Preparing pi-agent virtualenv"
  setup_agent

  echo "==> Ensuring uD3TN is available"
  build_ud3tn_if_needed

  cat <<EOF

Pi setup complete.

Next step:
  sudo bash scripts/start_pi_stack.sh

Notes:
  - start_pi_stack.sh will launch the Pi uD3TN node and the pi-agent together.
  - For redundant mode demos, set DTN_SOCKET_PATH_WIFI and DTN_SOCKET_PATH_LTE to different socket paths to start two Pi-side uD3TN sender sockets.
  - The management Ethernet interface should already be configured to reach ${MGMT_SERVER_IP}.
EOF
}

main "$@"
