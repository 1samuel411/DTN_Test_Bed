"""
GPS Reader service.

Reads NMEA sentences from the ArduSimple simplertk2b (u-blox ZED-F9P) over USB serial.
Parses $GNGGA / $GPGGA for altitude and fix quality.
Emits AltitudeTelemetry and GPSStatusMessage objects into the QueueManager.

Auto-detection:
  Scans /dev/ttyACM* and /dev/ttyUSB* for u-blox VID 0x1546 first;
  falls back to trying each candidate port at the configured baud rate.
"""

import asyncio
import logging
import time
from typing import Callable, Optional

import pynmea2
import serial
import serial.tools.list_ports

from config import (
    DEVICE_ID,
    DTN_NODE_ID,
    GPS_BAUDRATE,
    GPS_READ_INTERVAL_S,
    GPS_SEND_FREQUENCY_HZ,
)
from schemas import AltitudeTelemetry, GPSStatusMessage

logger = logging.getLogger(__name__)

# u-blox USB vendor ID (covers ZED-F9P and most u-blox modules)
UBLOX_VID = 0x1546

_FIX_LABELS = {
    0: "no_fix",
    1: "gps_fix",
    2: "dgps_fix",
    4: "rtk_fixed",
    5: "rtk_float",
    6: "estimated",
}


def _fix_label(quality: int) -> str:
    return _FIX_LABELS.get(quality, f"unknown_{quality}")


def detect_gps_port() -> Optional[str]:
    """
    Detect the GPS serial port.

    Priority:
      1. u-blox VID match on USB ports
      2. Any /dev/ttyACM* that is present (CDC-ACM, common for u-blox)
      3. Any /dev/ttyUSB* that is present (FTDI adapter)
    """
    ports = serial.tools.list_ports.comports()

    # 1. VID match
    for p in ports:
        if p.vid == UBLOX_VID:
            logger.info("GPS auto-detect: u-blox VID match on %s (%s)", p.device, p.description)
            return p.device

    # 2. CDC-ACM devices
    acm = sorted(p.device for p in ports if "ttyACM" in p.device)
    if acm:
        logger.info("GPS auto-detect: using first ttyACM: %s", acm[0])
        return acm[0]

    # 3. FTDI / generic USB serial
    usb = sorted(p.device for p in ports if "ttyUSB" in p.device)
    if usb:
        logger.info("GPS auto-detect: using first ttyUSB: %s", usb[0])
        return usb[0]

    logger.warning("GPS auto-detect: no candidate port found")
    return None


class GPSReader:
    """
    Reads NMEA from GPS, emits telemetry and status events.

    emit_cb: async callable that accepts TelemetryMessage objects.
    get_link_state: callable returning (active_mode, active_link, queue_depth).
    """

    def __init__(
        self,
        emit_cb: Callable,
        get_link_state: Callable,
        serial_port: str = "auto",
        baudrate: int = GPS_BAUDRATE,
        read_interval: float = GPS_READ_INTERVAL_S,
        send_frequency_hz: float = GPS_SEND_FREQUENCY_HZ,
    ) -> None:
        self._emit      = emit_cb
        self._link_state = get_link_state
        self._port_cfg  = serial_port
        self._baudrate  = baudrate
        self._interval  = read_interval
        self._send_interval_s = self._to_send_interval(send_frequency_hz)
        self._last_emit_monotonic = 0.0

        self._port: Optional[str]          = None
        self._ser:  Optional[serial.Serial] = None
        self._running   = False
        self._connected = False
        self._seq       = 0

        # Last known GPS state (for status-change detection)
        self._last_fix_quality: Optional[int] = None
        self._last_fix_state: str = "no_fix"

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def baudrate(self) -> int:
        return self._baudrate

    @property
    def generated_count(self) -> int:
        return self._seq

    @property
    def device(self) -> Optional[str]:
        return self._port

    @property
    def fix_state(self) -> str:
        return self._last_fix_state

    @property
    def send_frequency_hz(self) -> float:
        return round(1.0 / self._send_interval_s, 3)

    async def change_baudrate(self, new_baud: int) -> None:
        """Change baud rate live. Reopens serial port."""
        logger.info("Changing GPS baudrate: %d → %d", self._baudrate, new_baud)
        self._baudrate = new_baud
        if self._ser and self._ser.is_open:
            self._ser.close()
            self._connected = False
        await self._emit_status("baudrate_changed", baudrate=new_baud)

    async def change_send_frequency(self, hz: float) -> None:
        """Change telemetry emission frequency while keeping serial read loop running."""
        self._send_interval_s = self._to_send_interval(hz)
        self._last_emit_monotonic = 0.0
        await self._emit_status(
            "send_frequency_changed",
            details=f"hz={self.send_frequency_hz:.3f}",
        )

    async def run(self) -> None:
        """Main loop. Reconnects on serial errors."""
        self._running = True
        await self._emit_status("searching")

        while self._running:
            try:
                await self._open_port()
                await self._read_loop()
            except serial.SerialException as e:
                logger.error("GPS serial error: %s", e)
                if self._connected:
                    self._connected = False
                    await self._emit_status("serial_disconnected", details=str(e))
                await asyncio.sleep(5.0)
            except Exception as e:
                logger.exception("GPS reader unexpected error: %s", e)
                await asyncio.sleep(5.0)

    def stop(self) -> None:
        self._running = False
        if self._ser and self._ser.is_open:
            self._ser.close()

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _open_port(self) -> None:
        """Resolve and open the serial port."""
        if self._port_cfg == "auto":
            self._port = detect_gps_port()
        else:
            self._port = self._port_cfg

        if not self._port:
            logger.warning("No GPS port found, retrying in 5 s")
            await self._emit_status("searching", details="no port detected")
            await asyncio.sleep(5.0)
            return

        loop = asyncio.get_event_loop()
        self._ser = await loop.run_in_executor(
            None,
            lambda: serial.Serial(
                self._port,
                baudrate=self._baudrate,
                timeout=2.0,
            ),
        )
        self._connected = True
        logger.info("GPS serial opened: %s @ %d baud", self._port, self._baudrate)
        await self._emit_status("serial_connected", details=f"port={self._port}")

    async def _read_loop(self) -> None:
        """Read NMEA lines and parse altitude."""
        loop = asyncio.get_event_loop()

        while self._running and self._ser and self._ser.is_open:
            raw = await loop.run_in_executor(None, self._readline_safe)
            if raw is None:
                await asyncio.sleep(self._interval)
                continue

            try:
                line = raw.decode("ascii", errors="replace").strip()
            except Exception:
                continue

            if not line.startswith("$"):
                continue

            await self._parse_nmea(line)
            await asyncio.sleep(0)   # yield to event loop

    def _readline_safe(self) -> Optional[bytes]:
        try:
            return self._ser.readline()
        except serial.SerialException:
            raise
        except Exception:
            return None

    @staticmethod
    def _to_send_interval(hz: float) -> float:
        safe_hz = max(0.1, hz)
        return 1.0 / safe_hz

    async def _parse_nmea(self, line: str) -> None:
        """Parse one NMEA sentence. Emits messages on state change or on schedule."""
        # Only care about GGA sentences for altitude
        if not (line.startswith("$GNGGA") or line.startswith("$GPGGA")):
            return

        try:
            msg = pynmea2.parse(line)
        except pynmea2.ParseError as e:
            logger.debug("NMEA parse error: %s — line: %s", e, line[:80])
            await self._emit_status("parse_error", details=str(e))
            return

        fix_quality   = int(msg.gps_qual) if msg.gps_qual is not None else 0
        fix_state_str = _fix_label(fix_quality)
        altitude      = float(msg.altitude) if msg.altitude else 0.0
        num_sats      = int(msg.num_sats)   if msg.num_sats  else 0
        hdop_val      = float(msg.horizontal_dil) if msg.horizontal_dil else None

        # Emit a GPS status event on fix-state change
        if fix_quality != self._last_fix_quality:
            if fix_quality == 0:
                await self._emit_status("no_fix", fix_quality=fix_quality)
            else:
                await self._emit_status(
                    "fix_found",
                    details=f"quality={fix_quality} sats={num_sats}",
                    fix_quality=fix_quality,
                )
            self._last_fix_quality = fix_quality
            self._last_fix_state   = fix_state_str

        # Emit altitude telemetry at configured cadence (including no-fix).
        now = time.monotonic()
        if self._last_emit_monotonic and (now - self._last_emit_monotonic) < self._send_interval_s:
            return

        mode, link, depth = self._link_state()
        self._seq += 1

        telem = AltitudeTelemetry(
            sequence_number = self._seq,
            altitude        = altitude,
            fix_quality     = fix_quality,
            fix_state       = fix_state_str,
            num_satellites  = num_sats,
            hdop            = hdop_val,
            device_id       = DEVICE_ID,
            node_id         = DTN_NODE_ID,
            active_mode     = mode,
            active_link     = link,
            queue_depth     = depth,
        )
        await self._emit(telem)
        self._last_emit_monotonic = now

    async def _emit_status(
        self,
        event: str,
        details: Optional[str] = None,
        baudrate: Optional[int] = None,
        fix_quality: Optional[int] = None,
    ) -> None:
        status = GPSStatusMessage(
            event       = event,
            device_id   = DEVICE_ID,
            node_id     = DTN_NODE_ID,
            details     = details,
            baudrate    = baudrate or self._baudrate,
            fix_quality = fix_quality,
        )
        await self._emit(status)
