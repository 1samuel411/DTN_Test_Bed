#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAC_ENV="${REPO_ROOT}/mac-backend/.env"
BACKEND_DIR="${REPO_ROOT}/mac-backend"
FRONTEND_DIR="${REPO_ROOT}/frontend"
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
  need_file "${MAC_ENV}"
  load_env "${MAC_ENV}"

  local required=(
    DTN_NODE_ID
    DTN_SOCKET_PATH
    API_HOST
    API_PORT
    CONFIG_HOST
    CONFIG_PORT
    DB_PATH
  )

  for key in "${required[@]}"; do
    [[ -n "${!key:-}" ]] || die "mac-backend/.env is missing ${key}"
  done
}

install_brew_deps() {
  command -v brew >/dev/null 2>&1 || die "Homebrew is required on macOS. Install it from https://brew.sh first."
  brew install python node git cmake ninja pkg-config jansson
}

build_ud3tn_if_needed() {
  local brew_prefix
  brew_prefix="$(brew --prefix)"

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
      git submodule update --init --recursive && \
      CPATH="${brew_prefix}/include:${CPATH:-}" \
      LIBRARY_PATH="${brew_prefix}/lib:${LIBRARY_PATH:-}" \
      make -j"$(sysctl -n hw.logicalcpu)" ud3tn
    )
  fi

  [[ -x "${UD3TN_BIN}" ]] || die "uD3TN build failed. Expected binary at ${UD3TN_BIN}"
}

setup_backend() {
  local python_bin
  python_bin="$(command -v python3)"
  [[ -n "${python_bin}" ]] || die "python3 is required"

  "${python_bin}" -m venv "${BACKEND_DIR}/.venv"
  "${BACKEND_DIR}/.venv/bin/pip" install --upgrade pip
  "${BACKEND_DIR}/.venv/bin/pip" install -r "${BACKEND_DIR}/requirements.txt"
}

setup_frontend() {
  command -v npm >/dev/null 2>&1 || die "npm is required"
  (cd "${FRONTEND_DIR}" && npm install)
}

main() {
  [[ "$(uname -s)" == "Darwin" ]] || die "setup_mac.sh must be run on macOS"

  echo "==> Checking Mac configuration"
  check_config

  echo "==> Installing macOS dependencies"
  install_brew_deps

  echo "==> Preparing mac-backend virtualenv"
  setup_backend

  echo "==> Preparing frontend dependencies"
  setup_frontend

  echo "==> Ensuring uD3TN is available"
  build_ud3tn_if_needed

  cat <<EOF

Mac setup complete.

Next step:
  bash scripts/start_mac_stack.sh

Notes:
  - This starts the combined API/Configuration backend and the React web frontend.
  - Make sure your Mac Ethernet interface is configured as ${CONFIG_HOST} before starting the demo.
EOF
}

main "$@"
