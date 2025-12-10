"""
Logic layer for Modbus Monitor
- Serial communication (SerialManager)
- Modbus protocol (ModbusRTU)
- Background workers (PollWorker, PlotWorker, RRModeWorker)
- Data models (LoadMemory, InputRegDef, DtbptParser)
- Error logging (ModbusErrorLogger)
"""

import os
import time
import struct
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Any
from dataclasses import dataclass, field

from PyQt5 import QtCore

try:
    import serial
except ImportError:
    raise ImportError("Missing pyserial. Please install: pip install pyserial")


# ==================== Modbus RTU ====================
class ModbusRTU:
    """Modbus RTU protocol implementation"""

    EX_MAP = {
        1: "Illegal Function",
        2: "Illegal Data Address",
        3: "Illegal Data Value",
        4: "Slave Device Failure",
        5: "Acknowledge",
        6: "Slave Device Busy",
        8: "Memory Parity Error",
        10: "Gateway Path Unavailable",
        11: "Gateway Target Device Failed to Respond",
    }

    @staticmethod
    def crc16(data: bytes) -> int:
        """Calculate CRC-16 Modbus"""
        crc = 0xFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    @staticmethod
    def build_frame(slave_id: int, function: int, data: bytes) -> bytes:
        """Build Modbus frame with CRC"""
        frame = bytes([slave_id, function]) + data
        crc = ModbusRTU.crc16(frame)
        return frame + struct.pack("<H", crc)

    @staticmethod
    def read_holding_registers(slave_id: int, start_addr: int, quantity: int) -> bytes:
        """Build read holding registers request (0x03)"""
        if not (1 <= slave_id <= 247):
            raise ValueError(f"Invalid slave ID: {slave_id}")
        if not (1 <= quantity <= 125):
            raise ValueError(f"Invalid quantity: {quantity}")
        data = struct.pack(">HH", start_addr, quantity)
        return ModbusRTU.build_frame(slave_id, 0x03, data)

    @staticmethod
    def write_single_register(slave_id: int, addr: int, value: int) -> bytes:
        """Build write single register request (0x06)"""
        if not (1 <= slave_id <= 247):
            raise ValueError(f"Invalid slave ID: {slave_id}")
        if not (0 <= value <= 0xFFFF):
            raise ValueError(f"Invalid value: {value}")
        data = struct.pack(">HH", addr, value)
        return ModbusRTU.build_frame(slave_id, 0x06, data)

    @staticmethod
    def read_input_registers(slave_id: int, start_addr: int, quantity: int) -> bytes:
        """Build read input registers request (0x04)"""
        if not (1 <= slave_id <= 247):
            raise ValueError(f"Invalid slave ID: {slave_id}")
        if not (1 <= quantity <= 125):
            raise ValueError(f"Invalid quantity: {quantity}")
        data = struct.pack(">HH", start_addr, quantity)
        return ModbusRTU.build_frame(slave_id, 0x04, data)

    @staticmethod
    def parse_response(response: bytes, expected_slave: int, expected_func: int) -> Tuple[bool, Any]:
        """Parse Modbus response"""
        if len(response) < 5:
            return False, "Response too short"

        slave_id, func = response[0], response[1]
        if slave_id != expected_slave:
            return False, "Slave ID mismatch"

        # CRC check
        rx_crc = struct.unpack("<H", response[-2:])[0]
        calc_crc = ModbusRTU.crc16(response[:-2])
        if rx_crc != calc_crc:
            return False, "CRC error"

        # Exception
        if func & 0x80:
            if len(response) < 5:
                return False, "Exception frame too short"
            code = response[2]
            return False, ModbusRTU.EX_MAP.get(code, f"Exception 0x{code:02X}")

        if func != expected_func:
            return False, "Function mismatch"

        if func == 0x03:
            byte_count = response[2]
            expected_total = 5 + byte_count
            if len(response) != expected_total:
                return False, f"Length mismatch: got {len(response)}, expected {expected_total}"
            data = response[3:-2]
            if len(data) % 2 != 0:
                return False, "Byte count not even"
            values = [struct.unpack(">H", data[i:i+2])[0] for i in range(0, len(data), 2)]
            return True, values

        if func == 0x04:
            byte_count = response[2]
            expected_total = 5 + byte_count
            if len(response) != expected_total:
                return False, f"Length mismatch: got {len(response)}, expected {expected_total}"
            data = response[3:-2]
            if len(data) % 2 != 0:
                return False, "Byte count not even"
            values = [struct.unpack(">H", data[i:i+2])[0] for i in range(0, len(data), 2)]
            return True, values

        if func == 0x06:
            if len(response) != 8:
                return False, f"Write response length mismatch: {len(response)}"
            addr, value = struct.unpack(">HH", response[2:6])
            return True, (addr, value)

        # fallback raw
        return True, response[2:-2]


@dataclass
class LoadMemory:
    """Single source of truth for LoadSettings.dmem."""
    file_03: str = ""
    file_04: dict = field(default_factory=lambda: {
        "Normal": "", "Bypass": "", "Inverter": "", "Converter": "", "Gsensor": ""
    })
    file_alarm: str = ""  # Alarm definition file

    @classmethod
    def load(cls, path: Path = Path("./setting/LoadSettings.dmem")) -> "LoadMemory":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Normalize None -> "" and coerce to filenames (no None shown)
            def _nz(val: Any) -> str:
                try:
                    return "" if val is None else (str(val) if str(val).lower() != "none" else "")
                except Exception:
                    return ""
            return cls(
                file_03=_nz(data.get("file_03", "")),
                file_04={
                    "Normal": _nz(data.get("file_04_normal", "")),
                    "Bypass": _nz(data.get("file_04_bypass", "")),
                    "Inverter": _nz(data.get("file_04_inverter", "")),
                    "Converter": _nz(data.get("file_04_converter", "")),
                    "Gsensor": _nz(data.get("file_04_gsensor", ""))
                },
                file_alarm=_nz(data.get("file_alarm", ""))
            )
        except Exception:
            return cls()

    def save(self, path: Path = Path("./setting/LoadSettings.dmem")):
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "file_03": self.file_03,
            **{f"file_04_{k.lower()}": v for k, v in self.file_04.items()},
            "file_alarm": self.file_alarm
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Aliases for requested API naming
    @classmethod
    def read(cls) -> "LoadMemory":
        return cls.load()

    def write(self) -> None:
        self.save()


# ==================== Input Register Definition ====================
@dataclass
class InputRegDef:
    """Definition for a single 0x04 input register (IN0..IN7)"""
    title: str              # Display title (e.g., "Motor Temp", "IN0")
    fmt: str                # "value" or "bitstatus"
    ratio: float            # Multiplier for value display (default 1.0)
    show: Any               # For "value": "int16"|"uint16"; For "bitstatus": "1/0" or list of labels

    @staticmethod
    def create_default(index: int) -> 'InputRegDef':
        """Create default definition for INx"""
        return InputRegDef(
            title=f"IN{index}",
            fmt="value",
            ratio=1.0,
            show="int16"
        )


# ==================== Error Logger ====================
class ModbusErrorLogger:
    """Thread-safe error logger for Modbus communication errors"""

    MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

    def __init__(self, log_dir: str = "./log/err", log_filename: str = "Modbus_err.ddata"):
        self.log_dir = log_dir
        self.log_file = os.path.join(log_dir, log_filename)
        self._lock = QtCore.QMutex()
        self._ensure_log_directory()

    def log_error(self, port: str, baudrate: int, stage: str, attempt: int,
                  expected_slave: int, expected_func: int,
                  request: bytes, response: bytes, error: str):
        """Log a Modbus communication error to NDJSON file"""
        try:
            with QtCore.QMutexLocker(self._lock):
                # Check file size and rotate if needed
                self._rotate_if_needed()

                # Prepare log entry
                log_entry = {
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "port": port,
                    "baudrate": baudrate,
                    "stage": stage,
                    "attempt": attempt,
                    "expected_slave": expected_slave,
                    "expected_func": expected_func,
                    "request_hex": " ".join(f"{b:02X}" for b in request),
                    "response_hex": " ".join(f"{b:02X}" for b in response) if response else "",
                    "error": error
                }

                # Write to file (NDJSON format)
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception:
            # Silently ignore logging errors to not interfere with main communication
            pass

    def _ensure_log_directory(self):
        """Ensure log directory exists"""
        try:
            os.makedirs(self.log_dir, exist_ok=True)
        except Exception:
            pass

    def _rotate_if_needed(self):
        """Rotate log file if it exceeds MAX_FILE_SIZE"""
        try:
            if os.path.exists(self.log_file):
                if os.path.getsize(self.log_file) > self.MAX_FILE_SIZE:
                    # Create new filename with timestamp
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    new_name = os.path.join(self.log_dir, f"Modbus_err_{timestamp}.ddata")
                    os.rename(self.log_file, new_name)
        except Exception:
            pass


# ==================== Serial Manager ====================
class SerialManager(QtCore.QObject):
    """Thread-safe serial communication manager"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.port: Optional[serial.Serial] = None
        self.connected = False
        self.max_retries = 3
        self.inter_frame_delay = 0.01
        self._lock = QtCore.QMutex()
        self.io_lock = QtCore.QMutex()
        self.error_logger = ModbusErrorLogger()
        # Track connection info for error logging
        self.port_name = ""
        self.baudrate = 0

    def connect_port(self, port_name: str, baudrate: int, bytesize: int,
                     parity: str, stopbits: int, timeout: float) -> Tuple[bool, str]:
        """Connect to serial port"""
        with QtCore.QMutexLocker(self._lock):
            try:
                if self.connected:
                    return False, "Already connected"

                parity_map = {'N': serial.PARITY_NONE, 'E': serial.PARITY_EVEN, 'O': serial.PARITY_ODD}
                bytesize_map = {7: serial.SEVENBITS, 8: serial.EIGHTBITS}
                stopbits_map = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}

                self.port = serial.Serial(
                    port=port_name,
                    baudrate=baudrate,
                    bytesize=bytesize_map.get(bytesize, serial.EIGHTBITS),
                    parity=parity_map.get(parity, serial.PARITY_NONE),
                    stopbits=stopbits_map.get(stopbits, serial.STOPBITS_ONE),
                    timeout=timeout,
                    write_timeout=timeout
                )
                self.connected = True
                self.port_name = port_name
                self.baudrate = baudrate

                # calc inter-frame delay (3.5 chars)
                char_time = 11.0 / max(baudrate, 300)
                self.inter_frame_delay = max(3.5 * char_time, 0.00175)

                return True, f"Connected to {port_name}"
            except Exception as e:
                self.connected = False
                self.port = None
                return False, f"Connection failed: {e}"

    def disconnect_port(self) -> Tuple[bool, str]:
        """Disconnect from serial port"""
        with QtCore.QMutexLocker(self._lock):
            try:
                if self.port and self.port.is_open:
                    self.port.close()
                self.port = None
                self.connected = False
                return True, "Disconnected"
            except Exception as e:
                return False, f"Disconnect error: {e}"

    def _expected_response_length(self, func: int, request: bytes = None, buf: bytearray = None) -> int:
        """Calculate expected response length

        For 0x03/0x04: Pre-calculate from request quantity to reduce latency.
        For others: Calculate from response buffer when available.
        """
        if func == 0x06:
            return 8
        # Pre-calculate expected length from request for 0x03/0x04
        if func in (0x03, 0x04):
            if request and len(request) >= 6:
                # Extract quantity from request: bytes 4-5 (big-endian)
                qty = struct.unpack(">H", request[4:6])[0]
                # expected_len = 5 + (qty * 2)
                # 1 byte slave + 1 byte func + 1 byte count + (qty*2) data + 2 bytes CRC
                return 5 + (qty * 2)
            # Fallback: calculate from response buffer (old method)
            if buf and len(buf) >= 3:
                return 5 + buf[2]
            return 0
        return 0

    def transact(self, request: bytes, expected_slave: int, expected_func: int,
                 timeout: float = 0.5, post_quiet_ms: int = 0) -> Tuple[bool, Any]:
        """Perform Modbus transaction with automatic retries"""
        with QtCore.QMutexLocker(self._lock):
            if not self.connected or not self.port:
                return False, "Not connected"

        # do IO outside of lock but keep port ref
        port = self.port
        if port is None:
            return False, "Not connected"

        locker = QtCore.QMutexLocker(self.io_lock)
        try:
            for attempt in range(self.max_retries):
                try:
                    time.sleep(self.inter_frame_delay)

                    port.reset_input_buffer()
                    port.reset_output_buffer()
                    port.write(request)
                    port.flush()

                    start = time.time()
                    buf = bytearray()
                    # Pre-calculate expected length from request (for 0x03/0x04)
                    expected_len = self._expected_response_length(expected_func, request=request)

                    while (time.time() - start) < timeout:
                        chunk = port.read(256)
                        if chunk:
                            buf.extend(chunk)
                            # Update expected_len from response if not yet set
                            if not expected_len and len(buf) >= 2:
                                expected_len = self._expected_response_length(expected_func, buf=buf)
                            if expected_len and len(buf) >= expected_len:
                                break
                        else:
                            time.sleep(0.003)

                    if not buf:
                        if attempt < self.max_retries - 1:
                            time.sleep(0.05)
                            continue
                        # Log timeout error
                        error_msg = "Timeout - No response"
                        self.error_logger.log_error(
                            port=self.port_name,
                            baudrate=self.baudrate,
                            stage="timeout",
                            attempt=attempt + 1,
                            expected_slave=expected_slave,
                            expected_func=expected_func,
                            request=request,
                            response=b'',
                            error=error_msg
                        )
                        return False, error_msg

                    if expected_len and len(buf) < expected_len:
                        if attempt < self.max_retries - 1:
                            time.sleep(0.05)
                            continue
                        # Log incomplete response error
                        error_msg = f"Incomplete response ({len(buf)}/{expected_len} bytes)"
                        self.error_logger.log_error(
                            port=self.port_name,
                            baudrate=self.baudrate,
                            stage="incomplete_response",
                            attempt=attempt + 1,
                            expected_slave=expected_slave,
                            expected_func=expected_func,
                            request=request,
                            response=bytes(buf),
                            error=error_msg
                        )
                        return False, error_msg

                    success, result = ModbusRTU.parse_response(bytes(buf), expected_slave, expected_func)
                    if not success:
                        # Log parse error
                        self.error_logger.log_error(
                            port=self.port_name,
                            baudrate=self.baudrate,
                            stage="parse_error",
                            attempt=attempt + 1,
                            expected_slave=expected_slave,
                            expected_func=expected_func,
                            request=request,
                            response=bytes(buf),
                            error=result
                        )
                    return success, result

                except Exception as e:
                    if attempt < self.max_retries - 1:
                        time.sleep(0.05)
                        continue
                    # Log exception
                    error_msg = str(e)
                    self.error_logger.log_error(
                        port=self.port_name,
                        baudrate=self.baudrate,
                        stage="exception",
                        attempt=attempt + 1,
                        expected_slave=expected_slave,
                        expected_func=expected_func,
                        request=request,
                        response=b'',
                        error=error_msg
                    )
                    return False, error_msg

            return False, "Max retries exceeded"
        finally:
            if post_quiet_ms and post_quiet_ms > 0:
                time.sleep(post_quiet_ms / 1000.0)


# ==================== Polling Worker ====================
class PollWorker(QtCore.QThread):
    """Background thread for auto-polling registers"""

    sigRegister = QtCore.pyqtSignal(int, object, object)  # index, value|None, error|None
    sigInputRegisters = QtCore.pyqtSignal(object, object)  # values (list|None), error (str|None)
    sigModeIndicator = QtCore.pyqtSignal(object)  # value from register 0x0007 (0=Normal, non-0=Bypass)
    sigStatus = QtCore.pyqtSignal(str)

    def __init__(self, serial_mgr: SerialManager, get_row_addr_callable, get_cfg_callable, parent=None):
        super().__init__(parent)
        self.serial_mgr = serial_mgr
        self.get_row_addr = get_row_addr_callable  # returns addr int or None for row
        self.get_cfg = get_cfg_callable            # returns (slave_id:int, timeout:float, interval:float)
        self._running = True
        self._request_counter = 0

    def stop(self):
        """Stop the polling thread"""
        self._running = False

    def run(self):
        """Main polling loop"""
        # Short delay on startup to ensure clean serial state after restart
        time.sleep(0.1)

        while self._running:
            try:
                slave_id, timeout, interval = self.get_cfg()
            except Exception as e:
                self.sigStatus.emit(f"Invalid configuration: {e}")
                time.sleep(1.0)
                continue

            # Poll 10 holding registers (0x03)
            for i in range(10):
                if not self._running:
                    break

                addr = None
                try:
                    addr = self.get_row_addr(i)
                    if addr is None:
                        continue

                    req = ModbusRTU.read_holding_registers(slave_id, addr, 1)
                    ok, result = self.serial_mgr.transact(req, slave_id, 0x03, timeout=timeout)
                    if ok and isinstance(result, list) and result:
                        self.sigRegister.emit(i, int(result[0]), None)
                    else:
                        err = result if isinstance(result, str) else "Read failed"
                        self.sigRegister.emit(i, None, err)

                    self._request_counter += 1

                except Exception as e:
                    self.sigRegister.emit(i, None, str(e))

            # Every 20 requests, read input registers (0x04) - 20:1 ratio
            if self._request_counter >= 20:
                self._request_counter = 0
                if self._running:
                    # Array to store all 12 register values (0x00-0x07, 0x08-0x09, 0x0E-0x0F)
                    all_values = [None] * 12
                    error_msg = None

                    try:
                        # Request 1: Read 8 registers starting at 0x0000 (IN0-IN7)
                        req1 = ModbusRTU.read_input_registers(slave_id, 0x0000, 8)
                        ok1, result1 = self.serial_mgr.transact(req1, slave_id, 0x04, timeout=timeout)
                        if ok1 and isinstance(result1, list) and len(result1) == 8:
                            all_values[0:8] = result1
                        else:
                            error_msg = result1 if isinstance(result1, str) else "Read failed at 0x00"

                        # Request 2: Read 2 registers starting at 0x0008 (IN8-IN9)
                        req2 = ModbusRTU.read_input_registers(slave_id, 0x0008, 2)
                        ok2, result2 = self.serial_mgr.transact(req2, slave_id, 0x04, timeout=timeout)
                        if ok2 and isinstance(result2, list) and len(result2) == 2:
                            all_values[8:10] = result2
                        else:
                            err2 = result2 if isinstance(result2, str) else "Read failed at 0x08"
                            error_msg = error_msg + "; " + err2 if error_msg else err2

                        # Request 3: Read 2 registers starting at 0x000E (IN10-IN11)
                        req3 = ModbusRTU.read_input_registers(slave_id, 0x000E, 2)
                        ok3, result3 = self.serial_mgr.transact(req3, slave_id, 0x04, timeout=timeout)
                        if ok3 and isinstance(result3, list) and len(result3) == 2:
                            all_values[10:12] = result3
                        else:
                            err3 = result3 if isinstance(result3, str) else "Read failed at 0x0E"
                            error_msg = error_msg + "; " + err3 if error_msg else err3

                        # Emit results
                        if any(v is not None for v in all_values):
                            self.sigInputRegisters.emit(all_values, error_msg)
                        else:
                            self.sigInputRegisters.emit(None, error_msg or "All reads failed")
                            if error_msg and "timeout" in error_msg.lower():
                                self.sigStatus.emit("Input registers (0x04) timeout - will retry next cycle")
                    except Exception as e:
                        self.sigInputRegisters.emit(None, str(e))

            time.sleep(interval)


# ==================== Plot Worker ====================
class PlotWorker(QtCore.QThread):
    """Background thread for plotting with phase-locked 40ms requests.

    Reads 4 channels whose addresses are selected via CH1-CH4
    comboboxes in the UI. Requests occur on a fixed interval grid
    (default 40 ms per slot), cycling through enabled channels only.
    """

    sigData = QtCore.pyqtSignal(int, object, object)  # channel_index, value|None, timestamp|None
    sigModeIndicator = QtCore.pyqtSignal(object)  # value from register 0x0007 (0=Normal, non-0=Bypass)
    sigStatus = QtCore.pyqtSignal(str)

    def __init__(self, serial_mgr: SerialManager, get_addresses_callable, get_active_callable, get_cfg_callable, parent=None, req_interval_ms: int = 40):
        super().__init__(parent)
        self.serial_mgr = serial_mgr
        # Callable returning a list of 4 addresses (or None) for CH1-CH4
        self.get_addresses = get_addresses_callable
        # Callable returning list of enabled channel indices (e.g., [0, 1, 2, 3] or [0, 1, 3])
        self.get_active = get_active_callable
        self.get_cfg = get_cfg_callable              # returns (slave_id:int, timeout:float)
        self.req_interval_ms = max(1, int(req_interval_ms))
        self._running = True
        self._mode_check_counter = 0  # Counter for mode indicator check

    def stop(self):
        """Stop the plot worker thread"""
        self._running = False

    def run(self):
        """Phase-locked acquisition: enabled channels only on a 40ms grid."""
        # Use a high-resolution monotonic clock for scheduling
        interval_s = self.req_interval_ms / 1000.0
        base = time.perf_counter()
        slot_idx = 0  # increases every 40ms slot

        while self._running:
            try:
                # Always fetch latest config (slave, timeout)
                slave_id, timeout = self.get_cfg()
            except Exception as e:
                self.sigStatus.emit(f"Invalid configuration: {e}")
                time.sleep(1.0)
                continue

            # Compute scheduled start for this slot and align to grid
            scheduled = base + slot_idx * interval_s
            now = time.perf_counter()
            remaining = scheduled - now
            if remaining > 0:
                time.sleep(remaining)

            # Get list of enabled channel indices
            try:
                active_idxs = self.get_active()
            except Exception:
                active_idxs = []

            # If no channels are enabled, just idle (no IO)
            if not active_idxs:
                slot_idx += 1
                continue

            # Determine which channel to read this slot
            ch = active_idxs[slot_idx % len(active_idxs)]

            # Get addresses for all channels
            try:
                addresses = self.get_addresses() or []
            except Exception:
                addresses = []

            addr = None
            if isinstance(addresses, (list, tuple)) and len(addresses) > ch:
                addr = addresses[ch]

            # Timestamp for UI
            timestamp = time.time()

            # Perform Modbus read for this channel
            try:
                if addr is None:
                    # No address selected for this channel
                    self.sigData.emit(ch, None, timestamp)
                else:
                    req = ModbusRTU.read_holding_registers(slave_id, int(addr), 1)
                    ok, result = self.serial_mgr.transact(req, slave_id, 0x03, timeout=timeout)
                    if ok and isinstance(result, list) and result:
                        self.sigData.emit(ch, int(result[0]), timestamp)
                    else:
                        # On error, emit None
                        self.sigData.emit(ch, None, timestamp)
            except Exception:
                self.sigData.emit(ch, None, timestamp)

            # Advance to next 40ms slot without drifting the phase
            slot_idx += 1


# ==================== RR Mode Support ====================
@dataclass
class DtbptParser:
    """Parser for .dtbpt title files used in RR Mode"""
    pages: dict = field(default_factory=dict)  # page_num -> [title1, title2, title3, title4]

    @classmethod
    def load(cls, file_path: str) -> "DtbptParser":
        """Load .dtbpt file and parse page titles"""
        parser = cls()
        if not os.path.exists(file_path):
            return parser

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                current_page = None
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        # Check if it's a page header like "# page0"
                        if line.startswith('# page'):
                            try:
                                page_num = int(line.replace('# page', '').strip())
                                current_page = page_num
                            except ValueError:
                                pass
                        continue

                    # Parse comma-separated titles
                    if current_page is not None:
                        titles = [t.strip() for t in line.split(',')]
                        if len(titles) == 4:
                            parser.pages[current_page] = titles
                        current_page = None
        except Exception:
            pass

        return parser

    def get_titles(self, page: int) -> list:
        """Get titles for a specific page, or default titles if not found"""
        return self.pages.get(page, [f"Data{i+1}" for i in range(4)])


class RRModeWorker(QtCore.QThread):
    """Background thread for RR Mode (Rapid Response Mode) high-speed plotting.

    Protocol:
    1. Handshake: Send 52 52 00 [page] 00, receive 52
    2. Data Loop: Send 52 52 01 00 00, receive 72 [ii jj] [Data1-4] 0D
    3. End: Receive 58 to indicate data transmission complete

    Each data frame contains:
    - Data Group Index (big-endian 16-bit: ii*256 + jj): X-axis value
    - 4 data values (16-bit big-endian each): Y-axis values for 4 channels
    """

    sigFrame = QtCore.pyqtSignal(int, tuple)  # data_group_index, (d1, d2, d3, d4)
    sigStatus = QtCore.pyqtSignal(str)
    sigFinished = QtCore.pyqtSignal()

    def __init__(self, serial_mgr: SerialManager, page: int, timeout: float = 0.5, parent=None):
        super().__init__(parent)
        self.serial_mgr = serial_mgr
        self.page = page
        self.timeout = timeout
        self._running = True
        self._handshake_done = False

    def stop(self):
        """Stop the RR Mode worker thread"""
        self._running = False

    def run(self):
        """RR Mode main loop"""
        try:
            # Phase 1: Handshake
            if not self._do_handshake():
                self.sigStatus.emit("RR Mode handshake failed")
                self.sigFinished.emit()
                return

            self.sigStatus.emit(f"RR Mode started (Page {self.page})")

            # Phase 2: Data streaming loop
            while self._running:
                result = self._request_data_frame()
                if result == "END":
                    self.sigStatus.emit("RR Mode completed (received 58)")
                    break
                elif result == "ERROR":
                    # Continue to next request without retry
                    continue
                elif result is None:
                    # Timeout or no data
                    continue

        except Exception as e:
            self.sigStatus.emit(f"RR Mode error: {e}")
        finally:
            self.sigFinished.emit()

    def _do_handshake(self) -> bool:
        """Perform RR Mode handshake: 52 52 00 [page] 00 -> 52"""
        if not self.serial_mgr.connected or not self.serial_mgr.port:
            return False

        # Build handshake frame: 52 52 00 [page] 00
        handshake_frame = bytes([0x52, 0x52, 0x00, self.page & 0xFF, 0x00])

        try:
            port = self.serial_mgr.port
            if port is None:
                return False

            with QtCore.QMutexLocker(self.serial_mgr.io_lock):
                # Send handshake
                time.sleep(self.serial_mgr.inter_frame_delay)
                port.reset_input_buffer()
                port.reset_output_buffer()
                port.write(handshake_frame)
                port.flush()

                # Wait for response: 52
                start = time.time()
                while (time.time() - start) < self.timeout:
                    chunk = port.read(1)
                    if chunk and chunk[0] == 0x52:
                        self._handshake_done = True
                        return True

                return False
        except Exception:
            return False

    def _request_data_frame(self) -> Optional[str]:
        """Request one data frame: 52 52 01 00 00 -> 72 [ii jj] [Data1-4] 0D or 58

        Returns:
            "END" if received 58 (end marker)
            "ERROR" if frame parsing failed
            None if successful or timeout
        """
        if not self.serial_mgr.connected or not self.serial_mgr.port:
            return "ERROR"

        # Build request frame: 52 52 01 00 00
        request_frame = bytes([0x52, 0x52, 0x01, 0x00, 0x00])

        try:
            port = self.serial_mgr.port
            if port is None:
                return "ERROR"

            with QtCore.QMutexLocker(self.serial_mgr.io_lock):
                # Send request
                time.sleep(self.serial_mgr.inter_frame_delay)
                port.reset_input_buffer()
                port.reset_output_buffer()
                port.write(request_frame)
                port.flush()

                # Wait for response: 72 ... 0D (12 bytes) or 58 (1 byte)
                start = time.time()
                buf = bytearray()

                while (time.time() - start) < self.timeout:
                    chunk = port.read(256)
                    if chunk:
                        buf.extend(chunk)

                        # Check for end marker (58)
                        if len(buf) >= 1 and buf[0] == 0x58:
                            return "END"

                        # Check for complete data frame (72 ... 0D, 12 bytes)
                        if len(buf) >= 12 and buf[0] == 0x72 and buf[11] == 0x0D:
                            # Parse the frame
                            if self._parse_data_frame(buf[:12]):
                                return None  # Success
                            else:
                                return "ERROR"

                # Timeout
                return None
        except Exception:
            return "ERROR"

    def _parse_data_frame(self, frame: bytes) -> bool:
        """Parse data frame: 72 [ii jj] [Data1] [Data2] [Data3] [Data4] 0D

        Frame structure (12 bytes):
        [0]: 72 (header)
        [1-2]: Data Group Index [ii jj] where index = ii*256 + jj (big-endian)
               frame[1]=ii (high byte), frame[2]=jj (low byte)
        [3-4]: Data1 (big-endian)
        [5-6]: Data2 (big-endian)
        [7-8]: Data3 (big-endian)
        [9-10]: Data4 (big-endian)
        [11]: 0D (trailer)
        """
        if len(frame) != 12 or frame[0] != 0x72 or frame[11] != 0x0D:
            return False

        try:
            # Extract Data Group Index (X-axis) - big-endian 16-bit
            # ii*256 + jj where ii=frame[1], jj=frame[2]
            data_group_index = frame[1] * 256 + frame[2]

            # Extract 4 data values (Y-axis) - big-endian
            data_values = []
            for i in range(4):
                offset = 3 + i * 2
                value = struct.unpack(">H", frame[offset:offset+2])[0]
                data_values.append(value)

            # Emit one frame with all channel data
            self.sigFrame.emit(data_group_index, tuple(data_values))

            return True
        except Exception:
            return False
