SD card (boot partition only): SSH + static 192.168.4.2 for direct Mac link
============================================================================

What prepare_boot_volume.sh does
--------------------------------
1. Creates empty file `ssh` on the FAT volume → SSH enabled on boot.
2. Edits `cmdline.txt` (with a timestamped .bak backup):
   - Removes all `systemd.*` tokens (old one-shot firstrun that often ran too early).
   - Removes any previous `ip=...` token.
   - Appends a kernel **ip=** static address so the interface comes up **before**
     NetworkManager / cloud-init (fixes many "Host is down" / ARP incomplete cases).

Default kernel line ends with something like:
  ip=192.168.4.2::192.168.4.1:255.255.255.0::eth0:off

On the Mac, set the same Ethernet/USB-LAN to **192.168.4.1**, mask **255.255.255.0**.

Run (SD mounted, e.g. bootfs)
-----------------------------
  bash scripts/sd-first-boot/prepare_boot_volume.sh /Volumes/bootfs

If your Pi uses **end0** instead of **eth0** (check with `ip link` if you have a monitor):
  PI_ETHER_IF=end0 bash scripts/sd-first-boot/prepare_boot_volume.sh /Volumes/bootfs

Optional env vars
-----------------
  PI_STATIC_IP   (default 192.168.4.2)
  PI_MAC_GATEWAY (default 192.168.4.1)
  PI_NETMASK     (default 255.255.255.0)
  PI_ETHER_IF    (default eth0)

Then
----
  diskutil eject /Volumes/bootfs
  Boot Pi, wait ~1–2 min, then:
    ping 192.168.4.2
    ssh pi@192.168.4.2

firstrun.sh (legacy)
--------------------
Older copies of `firstrun.sh` in this folder are **not** used by `prepare_boot_volume.sh`
anymore. Networking is handled by kernel **ip=** only.
