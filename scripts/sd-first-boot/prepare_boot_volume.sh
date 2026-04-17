#!/usr/bin/env bash
# Run on your Mac with the Pi SD card's FAT boot partition mounted.
# Usage: ./prepare_boot_volume.sh /Volumes/bootfs
#
# - Enables SSH (empty "ssh" file)
# - Rewrites cmdline.txt: strips systemd.run / firstrun junk, sets kernel "ip=" static IPv4
#   (works before NetworkManager — fixes "Host is down" when NM never applied)
# - Removes stale firstrun.sh from the boot volume (optional; harmless if missing)
#
# Override interface if not eth0 (some boards use end0):
#   PI_ETHER_IF=end0 ./prepare_boot_volume.sh /Volumes/bootfs

set -euo pipefail

BOOT="${1:?Usage: $0 /Volumes/bootfs}"

[[ -d "${BOOT}" ]] || {
  echo "Not a directory: ${BOOT}" >&2
  exit 1
}
[[ -f "${BOOT}/cmdline.txt" ]] || {
  echo "No cmdline.txt — use the Pi boot (FAT) partition." >&2
  exit 1
}

PI_IP="${PI_STATIC_IP:-192.168.4.2}"
MAC_GW="${PI_MAC_GATEWAY:-192.168.4.1}"
MASK="${PI_NETMASK:-255.255.255.0}"
IFACE="${PI_ETHER_IF:-eth0}"

# Kernel nfsroot "ip=" format (see kernel nfsroot docs)
IP_TOKEN="ip=${PI_IP}::${MAC_GW}:${MASK}::${IFACE}:off"

cp "${BOOT}/cmdline.txt" "${BOOT}/cmdline.txt.bak.$(date +%s)"
touch "${BOOT}/ssh"
rm -f "${BOOT}/firstrun.sh"

export BOOT_VOL="${BOOT}"
export IP_TOKEN="${IP_TOKEN}"

python3 <<'PY'
import os
from pathlib import Path

boot = Path(os.environ["BOOT_VOL"])
cmd = boot / "cmdline.txt"
ip_tok = os.environ["IP_TOKEN"]

text = cmd.read_text().replace("\r\n", "\n")
line = text.strip().split("\n", 1)[0].strip()
parts = line.split()
drop = ("systemd.run=", "systemd.run_success_action=", "systemd.unit=")
kept = [
    p
    for p in parts
    if not any(p.startswith(d) for d in drop)
    and not p.startswith("ip=")
]
kept.append(ip_tok)
out = " ".join(kept) + "\n"
cmd.write_text(out)
PY

echo "OK: ${BOOT}/cmdline.txt now includes: ${IP_TOKEN}"
echo "     (and systemd.* / old ip= tokens were removed). ssh file touched."
echo "Eject SD, boot Pi, Mac Ethernet = ${MAC_GW}/24, then: ping ${PI_IP} && ssh pi@${PI_IP}"
