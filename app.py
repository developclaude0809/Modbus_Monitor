"""
Enhanced Modbus RTU Controller with PyQt5
- 9-color themed UI (Midnight Navy, Deep/ Sky Blue, Soft Yellow, Cream Tint, Cool Gray, Mist Blue, Rose Coral, Mint Glow)
- Proper threading with QThread and signals
- Modbus protocol support (0x03 Read, 0x06 Write)
- Auto-polling with configurable intervals
- Address definition file support (.ddata)
- Searchable combobox with mouse wheel support
- Thread-safe serial communication
"""

import os
import sys
import time
import struct
import bisect
import ctypes
import json
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Any, List
from dataclasses import dataclass, field

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtGui import QIcon

# ==================== DEFAULTS ====================
# Centralized defaults for timing values (milliseconds)
DEFAULT_TIMEOUT_MS = 40
DEFAULT_POLL_INTERVAL_MS = 50

# ---------- pyserial ----------
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.exit("Missing pyserial. Please install: pip install pyserial")

# ---------- matplotlib for plotting ----------
try:
    import matplotlib
    matplotlib.use('Qt5Agg')
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT
    from matplotlib.figure import Figure
    import matplotlib.pyplot as plt
except ImportError:
    sys.exit("Missing matplotlib. Please install: pip install matplotlib")


# ==================== COLOR CONFIGURATION ====================
# Unified color palette sorted by RGB order for easy modification

class Colors:
    # ------------------------------------------------------------
    # MASTER COLOR PALETTE (Sorted by RGB hex values)
    # ------------------------------------------------------------
    BTN_DANGER_BG     = "#A32424"
    BTN_SUCCESS_HOVER = "#10B97B"
    BTN_SUCCESS_BG    = "#059661"
    MIDNIGHT_NAVY     = "#0F172A"
    DEEP_BLUE         = "#2563EB"
    MIDNIGHT_OCEAN    = "#3282b8"
    COOL_GRAY         = "#1E293B"
    SKY_BLUE          = "#60A5FA"
    MIST_BLUE         = "#38BDF8"
    MINT_GLOW         = "#34D399"
    SOFT_YELLOW       = "#F4F27E"
    CREAM_TINT        = "#FFF5C2"
    ROSE_CORAL        = "#F87171"
    BENIUKON          = "#E98B2A"
    BG_INPUT          = "#334155"
    AKAKUCHIBA        = "#C78550"
    BTN_TEXT_COLOR    = "#FFFFFF"

    # ------------------------------------------------------------
    # SEMANTIC COLORS Contextual mapping for dark UI
    # ------------------------------------------------------------

    # Backgrounds
    BG_APP         = MIDNIGHT_NAVY
    BG_PANEL       = COOL_GRAY
    BG_INPUT_COLOR = BG_INPUT
    BG_BUTTON      = DEEP_BLUE
    BG_HEADER      = COOL_GRAY

    # Text
    TEXT_PRIMARY   = CREAM_TINT
    TEXT_ON_DARK   = CREAM_TINT
    TEXT_LABEL     = MIST_BLUE

    # Borders
    BORDER_NORMAL  = MIST_BLUE
    BORDER_FOCUS   = SKY_BLUE
    BORDER_PANEL   = MIST_BLUE

    # Buttons
    BTN_PRIMARY_BG     = DEEP_BLUE
    BTN_PRIMARY_TEXT   = CREAM_TINT
    BTN_PRIMARY_COLOR  = BTN_TEXT_COLOR
    BTN_PRIMARY_HOVER  = SKY_BLUE

    BTN_DANGER_HOVER   = ROSE_CORAL

    BTN_SUCCESS_BG     = BTN_SUCCESS_BG
    BTN_SUCCESS_HOVER  = BTN_SUCCESS_HOVER

    BTN_SECONDARY_BG   = DEEP_BLUE
    BTN_SECONDARY_HOVER= MIST_BLUE

    # Status & Special Elements
    STATUS_ERROR       = ROSE_CORAL
    STATUS_SUCCESS     = MINT_GLOW
    STATUS_NORMAL      = SOFT_YELLOW

    ROW_NUMBER_BG      = DEEP_BLUE
    ROW_NUMBER_TEXT    = CREAM_TINT

    VALUE_DISPLAY_BG   = COOL_GRAY
    VALUE_DISPLAY_TEXT = CREAM_TINT
# =============================================================


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
                }
            )
        except Exception:
            return cls()

    def save(self, path: Path = Path("./setting/LoadSettings.dmem")):
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "file_03": self.file_03,
            **{f"file_04_{k.lower()}": v for k, v in self.file_04.items()}
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
    sigInputRegisters = QtCore.pyqtSignal(object, object)  # FIXED: Changed from (list, object) to (object, object) - values (list|None), error (str|None)
    sigModeIndicator = QtCore.pyqtSignal(object)  # value from register 0x0007 (0=Normal, non-0=Bypass)
    sigStatus = QtCore.pyqtSignal(str)

    def __init__(self, serial_mgr: SerialManager, get_row_addr_callable, get_cfg_callable, parent=None):
        super().__init__(parent)
        self.serial_mgr = serial_mgr
        self.get_row_addr = get_row_addr_callable  # returns addr int or None for row
        self.get_cfg = get_cfg_callable            # returns (slave_id:int, timeout:float, interval:float)
        self._running = True
        self._request_counter = 0  # FIXED: Count individual 0x03 requests, not cycles

    def stop(self):
        """Stop the polling thread"""
        self._running = False

    def run(self):
        """Main polling loop"""
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

                    # FIXED: Increment request counter after each successful 0x03 request
                    self._request_counter += 1

                except Exception as e:
                    self.sigRegister.emit(i, None, str(e))

            # FIXED: Every 20 requests (not cycles), read input registers (0x04) - 20:1 ratio
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
                            # FIXED: Emit explicit status message for timeouts
                            if error_msg and "timeout" in error_msg.lower():
                                self.sigStatus.emit("Input registers (0x04) timeout - will retry next cycle")
                    except Exception as e:
                        self.sigInputRegisters.emit(None, str(e))

                    # DISABLED: Mode indicator now queried only on button clicks (Connect/Start/Draw)
                    # # Read mode indicator register 0x0007 (0x03 holding register)
                    # try:
                    #     req_mode = ModbusRTU.read_holding_registers(slave_id, 0x0007, 1)
                    #     ok_mode, result_mode = self.serial_mgr.transact(req_mode, slave_id, 0x03, timeout=timeout)
                    #     if ok_mode and isinstance(result_mode, list) and result_mode:
                    #         self.sigModeIndicator.emit(int(result_mode[0]))
                    #     else:
                    #         self.sigModeIndicator.emit(None)
                    # except Exception:
                    #     self.sigModeIndicator.emit(None)

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

            # DISABLED: Mode indicator now queried only on button clicks (Connect/Start/Draw)
            # # Check mode indicator every 20 slots
            # self._mode_check_counter += 1
            # if self._mode_check_counter >= 20:
            #     self._mode_check_counter = 0
            #     try:
            #         req_mode = ModbusRTU.read_holding_registers(slave_id, 0x0007, 1)
            #         ok_mode, result_mode = self.serial_mgr.transact(req_mode, slave_id, 0x03, timeout=timeout)
            #         if ok_mode and isinstance(result_mode, list) and result_mode:
            #             self.sigModeIndicator.emit(int(result_mode[0]))
            #         else:
            #             self.sigModeIndicator.emit(None)
            #     except Exception:
            #         self.sigModeIndicator.emit(None)

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


# ==================== UI Helpers ====================
class SearchableCombo(QtWidgets.QComboBox):
    """
    No-filter searchable combo:
    - Typing does NOT change the current value and does NOT filter items.
    - Opening the popup (or pressing Down) auto-highlights the first item that CONTAINS the typed text (case-insensitive).
    - Arrow keys move the highlight only; click or Enter commits.
    - Supports mouse wheel scrolling when hovered/focused.
    - API-compatible with QComboBox (addItem, addItems, clear, etc.)
    """

    def __init__(self, parent=None, half_width=True):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setCompleter(None)  # disable built-in completer

        # Model: no proxy, no filtering
        self._model = QtGui.QStandardItemModel(self)
        super().setModel(self._model)
        self.setModelColumn(0)

        # State
        self._allow_commit = False
        self._popup_open = False
        self._hovered = False

        # Event filters
        self.installEventFilter(self)            # block built-in type-to-select
        self.lineEdit().installEventFilter(self) # Down/F4/Enter handling
        self.view().installEventFilter(self)     # arrow navigation without committing
        self.setMouseTracking(True)

        # Connections
        self.view().clicked.connect(self._on_view_activate)
        self.view().pressed.connect(self._on_view_activate)
        # Ensure the editable display text is left-aligned
        try:
            self.lineEdit().setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        except Exception:
            pass

        # Ensure initial view shows beginning of text
        QtCore.QTimer.singleShot(0, self._reset_cursor_to_start)

        # Set width to half if requested
        if half_width:
            self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
            self.setMaximumWidth(150)

        # Apply stylesheet if Colors class is available
        try:
            self.setStyleSheet(
                f"""
                QComboBox {{
                    background-color: {Colors.BG_INPUT};
                    color: {Colors.TEXT_PRIMARY};
                    border: 2px solid {Colors.BORDER_NORMAL};
                    border-radius: 6px;
                    padding: 6px 8px;
                }}
                QComboBox:focus {{
                    border: 2px solid {Colors.BORDER_FOCUS};
                }}
                QComboBox QAbstractItemView {{
                    background: {Colors.BG_INPUT};
                    color: {Colors.TEXT_PRIMARY};
                    border: 2px solid {Colors.BORDER_NORMAL};
                    selection-background-color: {Colors.SOFT_YELLOW};
                    selection-color: {Colors.MIDNIGHT_NAVY};
                }}
                """
            )
        except (NameError, AttributeError):
            pass  # Colors not available, skip styling

    # ----- Core behavior -----
    def showPopup(self):
        """Show popup and auto-highlight first match"""
        super().showPopup()
        self._popup_open = True
        QtCore.QTimer.singleShot(0, self._highlight_first_match)

    def hidePopup(self):
        """Hide popup and reset state"""
        self._popup_open = False
        super().hidePopup()
        # After popup closes, show beginning of the text
        QtCore.QTimer.singleShot(0, self._reset_cursor_to_start)

    def _highlight_first_match(self):
        """Highlight first item that contains the typed text"""
        text = self.lineEdit().text().casefold()
        target_row = None

        if text:
            # Find first item containing the typed text
            for row in range(self._model.rowCount()):
                val = self._model.item(row).text()
                if text in val.casefold():
                    target_row = row
                    break

        # If no match or no text, keep current index
        if target_row is None:
            target_row = max(0, self.currentIndex())

        # Highlight the target row
        idx = self.model().index(target_row, 0)
        self.view().setCurrentIndex(idx)
        self.view().selectionModel().setCurrentIndex(idx, QtCore.QItemSelectionModel.ClearAndSelect)
        self.view().scrollTo(idx, QtWidgets.QAbstractItemView.PositionAtCenter)

    def _commit_row(self, row: int):
        """Commit selection to specified row"""
        self._allow_commit = True
        try:
            super().setCurrentIndex(row)
        finally:
            self._allow_commit = False
        # After committing a row, show beginning of the text
        QtCore.QTimer.singleShot(0, self._reset_cursor_to_start)

    def _on_view_activate(self, mi: QtCore.QModelIndex):
        """Handle click/press on popup item"""
        if not mi.isValid():
            return
        self._commit_row(mi.row())
        self.hidePopup()

    def setCurrentIndex(self, index: int):
        """Override to block non-explicit commits (e.g., highlight moves)"""
        if self._allow_commit or index == -1:
            return super().setCurrentIndex(index)
        # Otherwise ignore (prevents typing from changing value)

    # ----- Event filtering -----
    def eventFilter(self, obj, ev):
        """Handle keyboard events for search and navigation"""
        # Block built-in type-to-select so typing doesn't jump value
        if obj is self and ev.type() == QtCore.QEvent.ShortcutOverride:
            if ev.text() and not (ev.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)):
                ev.accept()
                return True

        # Line edit: open/close popup; Enter to commit highlighted when open
        if obj is self.lineEdit() and ev.type() == QtCore.QEvent.KeyPress:
            key = ev.key()
            if key in (QtCore.Qt.Key_Down, QtCore.Qt.Key_F4):
                if self._popup_open:
                    self.hidePopup()
                else:
                    self.showPopup()
                return True
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                if self._popup_open:
                    mi = self.view().currentIndex()
                    if mi.isValid():
                        self._on_view_activate(mi)
                return True

        # Popup list: arrow keys move highlight only; no commit
        if obj is self.view() and ev.type() == QtCore.QEvent.KeyPress:
            if ev.key() in (
                QtCore.Qt.Key_Up, QtCore.Qt.Key_Down,
                QtCore.Qt.Key_PageUp, QtCore.Qt.Key_PageDown,
                QtCore.Qt.Key_Home, QtCore.Qt.Key_End
            ):
                QtWidgets.QAbstractItemView.keyPressEvent(self.view(), ev)
                return True

        return super().eventFilter(obj, ev)

    # ----- Mouse wheel support -----
    def enterEvent(self, event: QtCore.QEvent):
        """Track hover state for wheel scrolling"""
        self._hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent):
        """Track hover state for wheel scrolling"""
        self._hovered = False
        super().leaveEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent):
        """Scroll items when hovered or focused; do not open popup"""
        if self._hovered or self.hasFocus():
            cnt = self.count()
            if cnt > 0:
                delta = event.angleDelta().y()
                current = self.currentIndex()
                if delta > 0:
                    new_idx = (current - 1) % cnt
                elif delta < 0:
                    new_idx = (current + 1) % cnt
                else:
                    return
                # Use commit to actually change the value
                self._commit_row(new_idx)
        else:
            event.ignore()

    # ----- Cursor management -----
    def _reset_cursor_to_start(self):
        """Move cursor to start so the beginning of text is visible."""
        try:
            le = self.lineEdit()
            if le is not None:
                le.setCursorPosition(0)
        except Exception:
            pass

    def focusOutEvent(self, event: QtGui.QFocusEvent):
        """When losing focus, ensure the beginning is visible."""
        super().focusOutEvent(event)
        QtCore.QTimer.singleShot(0, self._reset_cursor_to_start)

    # ----- API compatibility methods -----
    def addItem(self, text, userData=None):
        """Add item to model (API-compatible with QComboBox)"""
        item = QtGui.QStandardItem(str(text))
        # Make sure popup list text is left-aligned
        item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        if userData is not None:
            item.setData(userData, QtCore.Qt.UserRole)
        self._model.appendRow(item)

    def addItems(self, texts):
        """Add multiple items to model (API-compatible with QComboBox)"""
        for text in texts:
            self.addItem(text)

    def clear(self):
        """Clear all items (API-compatible with QComboBox)"""
        self._model.clear()

    def count(self):
        """Return number of items"""
        return self._model.rowCount()

    def currentData(self, role=QtCore.Qt.UserRole):
        """Get data associated with current item (API-compatible with QComboBox)"""
        idx = self.currentIndex()
        if idx < 0 or idx >= self._model.rowCount():
            return None
        item = self._model.item(idx)
        if item is None:
            return None
        return item.data(role)

    def itemData(self, index, role=QtCore.Qt.UserRole):
        """Get data associated with item at index (API-compatible with QComboBox)"""
        if index < 0 or index >= self._model.rowCount():
            return None
        item = self._model.item(index)
        if item is None:
            return None
        return item.data(role)

    def setModel(self, model):
        """Override setModel for external compatibility"""
        if model != self._model:
            self._model = model
            super().setModel(self._model)


class AddressCombo(QtWidgets.QComboBox):
    """Deprecated: not used; preserved for backward compatibility."""
    pass


class ClickableLabel(QtWidgets.QLabel):
    """QLabel that emits a clicked signal when pressed"""
    clicked = QtCore.pyqtSignal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        """Emit clicked signal on mouse press"""
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# ==================== UI Auto-Scaling ====================
def clamp(val, lo, hi):
    """Clamp value between low and high bounds"""
    return max(lo, min(hi, val))


def compute_ui_scale(app, base_w=2560, base_h=1440, lo=0.85, hi=1.25):
    """Compute UI scale factor based on screen resolution"""
    screen = app.primaryScreen()
    geom = screen.availableGeometry()
    sw, sh = geom.width(), geom.height()
    s = min(sw / float(base_w), sh / float(base_h))
    return max(lo, min(hi, s))


class UiTokens:
    """Unified design tokens for consistent UI sizing and responsive layout"""

    def __init__(self, scale: float):
        self.scale = scale
        self.s = clamp(scale, 0.9, 1.15)

    def btn_h(self):
        """Standard button height - scales with display"""
        return int(clamp(36 * self.s, 32, 44))

    def btn_h_large(self):
        """Large button height for prominent controls (motor, reset panels)"""
        return int(clamp(50 * self.s, 42, 58))

    def btn_w(self):
        """Standard button minimum width - responsive"""
        return int(clamp(120 * self.s, 100, 140))

    def input_h(self):
        """Input field height"""
        return int(clamp(34 * self.s, 30, 42))

    def input_h_large(self):
        """Large input field height for prominent inputs"""
        return int(clamp(50 * self.s, 42, 58))

    def pad(self):
        """Padding size"""
        return int(clamp(10 * self.s, 8, 14))

    def gap(self):
        """Gap/spacing size"""
        return int(clamp(8 * self.s, 6, 12))

    def radius(self):
        """Border radius"""
        return int(clamp(8 * self.s, 6, 12))

    def icon(self):
        """Icon size"""
        return int(clamp(20 * self.s, 16, 24))

    def panel_minw(self):
        """Panel minimum width"""
        return int(clamp(520 * self.s, 460, 640))

    def panel_h_control(self):
        """Control panel minimum height (RD, Reset panels)"""
        return int(clamp(80 * self.s, 70, 95))

    def combo_w(self):
        """Combo box minimum width"""
        return int(clamp(140 * self.s, 120, 160))

    # Font size tokens - scale with display DPI
    def font_small(self):
        """Small font size (10px base)"""
        return int(clamp(10 * self.s, 9, 12))

    def font_normal(self):
        """Normal font size (14px base)"""
        return int(clamp(14 * self.s, 12, 16))

    def font_medium(self):
        """Medium font size (16px base)"""
        return int(clamp(16 * self.s, 14, 18))

    def font_large(self):
        """Large font size (22px base - for combo/inputs)"""
        return int(clamp(22 * self.s, 19, 26))

    def font_xlarge(self):
        """Extra large font size (24-26px base - for prominent buttons)"""
        return int(clamp(25 * self.s, 22, 29))


def style_consistent(app: QtWidgets.QApplication, tokens: UiTokens):
    """Apply consistent styling based on UI tokens (minimal override to preserve theme)"""
    # Only apply non-intrusive scaling adjustments, don't override the main theme
    pass  # Keep existing theme intact


def apply_control_sizes(root: QtWidgets.QWidget, tokens: UiTokens):
    """Apply size constraints to all controls based on UI tokens"""
    # Disabled: The existing UI already has good sizing
    # Only apply if there are specific scaling issues
    pass


# ==================== Load Settings Dialog ====================
class DeviceInformationDialog(QtWidgets.QDialog):
    """Non-modal dialog to display firmware version and device information"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Fan Information.")
        self.setMinimumWidth(540)
        self.setMinimumHeight(350)

        # Make it non-modal and delete on close
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        # Firmware version registers (addresses 19-23, 0x13-0x17)
        self.version_registers = [19, 20, 21, 22, 23]

        # Device info register definitions (addresses 24-34, 0x18-0x22)
        # Order: Speed Max, Speed Min, Speed Stop, Power, Duty Max, Duty Min, OC, OV, UV, OT
        self.device_registers = [
            {"label": "Speed Max", "addr": 24, "scale": 1.0, "unit": "RPM"},
            {"label": "Speed Min", "addr": 25, "scale": 1.0, "unit": "RPM"},
            {"label": "Speed Stop", "addr": 26, "scale": 1.0, "unit": "RPM"},
            {"label": "Power", "addr": 29, "scale": 1.0, "unit": "W"},
            {"label": "Duty Max", "addr": 27, "scale": 0.1, "unit": "%"},
            {"label": "Duty Min", "addr": 28, "scale": 0.1, "unit": "%"},
            {"label": "OC", "addr": 30, "scale": 0.001, "unit": "A"},
            {"label": "OV", "addr": 31, "scale": 1.0, "unit": "V"},
            {"label": "UV", "addr": 32, "scale": 1.0, "unit": "V"},
            # Address 33 (SV) is skipped as per specification
            {"label": "OT", "addr": 34, "scale": 0.1, "unit": "°C"},
        ]

        # Store data labels for update
        self.data_labels = []

        self._build_ui()

    def _build_ui(self):
        """Build dialog UI"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 12, 12, 12)

        # Title
        title = QtWidgets.QLabel("Fan Information.")
        title.setFixedHeight(35)
        title.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        title.setStyleSheet(f"font-size:20px; font-weight:700; color:{Colors.TEXT_PRIMARY}; border:none;")
        layout.addWidget(title)

        # Firmware Version and Last Update in same row
        version_row = QtWidgets.QHBoxLayout()
        self.lbl_firmware = QtWidgets.QLabel("Firmware Version : ----/----/--")
        self.lbl_firmware.setFixedHeight(30)
        self.lbl_firmware.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.lbl_firmware.setStyleSheet(f"font-size:14px; font-weight:600; color:{Colors.TEXT_PRIMARY}; border:none;")
        version_row.addWidget(self.lbl_firmware)

        version_row.addStretch()

        self.lbl_last_update = QtWidgets.QLabel("Last update: Never")
        self.lbl_last_update.setFixedHeight(30)
        self.lbl_last_update.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.lbl_last_update.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-size:11px; border:none;")
        version_row.addWidget(self.lbl_last_update)

        layout.addLayout(version_row)

        # Data display frame (similar to 04 input register display)
        # Calculate height: margins(3+3) + 5_rows(35*5) + 4_gaps(2*4) = 189px
        data_frame = QtWidgets.QFrame()
        data_frame.setFixedHeight(189)
        data_frame.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:2px solid {Colors.BORDER_PANEL}; border-radius:6px;}}")

        # Create grid layout (2 columns for compact display)
        data_grid = QtWidgets.QGridLayout(data_frame)
        data_grid.setContentsMargins(3, 3, 3, 3)
        data_grid.setHorizontalSpacing(8)
        data_grid.setVerticalSpacing(2)

        # Create label pairs for each register (2 columns layout)
        self.data_labels = []
        for i, reg in enumerate(self.device_registers):
            row = i // 2  # 2 items per row
            col = i % 2

            # Create horizontal container for label + value
            container = QtWidgets.QWidget()
            container.setFixedHeight(35)
            hbox = QtWidgets.QHBoxLayout(container)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.setSpacing(8)

            # Label name (left side)
            label_name = QtWidgets.QLabel(reg['label'])
            label_name.setFixedWidth(100)
            label_name.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            label_name.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700; font-size:14px; padding:4px;")
            hbox.addWidget(label_name)

            # Value display (styled like 04 input registers)
            label_data = QtWidgets.QLabel("----")
            label_data.setAlignment(QtCore.Qt.AlignCenter)
            label_data.setStyleSheet(
                f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; "
                f"padding:4px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; "
                f"font-weight:600; font-size:16px;"
            )
            hbox.addWidget(label_data)

            # Store reference to data label for updates
            self.data_labels.append(label_data)

            # Add to grid
            data_grid.addWidget(container, row, col)

        layout.addWidget(data_frame)

        # Button layout
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()

        # Refresh button
        self.btn_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_refresh.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:14px; padding:8px 20px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}"
        )
        self.btn_refresh.clicked.connect(self._refresh_data)
        btn_layout.addWidget(self.btn_refresh)

        # Close button
        self.btn_close = QtWidgets.QPushButton("Close")
        self.btn_close.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:14px; padding:8px 20px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        self.btn_close.clicked.connect(self.close)
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout)

        # Set dialog background
        self.setStyleSheet(f"QDialog{{background:{Colors.BG_PANEL};}}")

    def _refresh_data(self):
        """Read firmware version and device information from Modbus"""
        if not self.parent_window:
            QtWidgets.QMessageBox.warning(self, "Error", "Parent window not available")
            return

        # Check if connected
        if not hasattr(self.parent_window, 'ser') or not self.parent_window.ser or not self.parent_window.ser.is_open:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Please connect to a device first")
            return

        # Get slave ID from parent
        try:
            slave_id = int(self.parent_window.edSlave.text())
        except:
            slave_id = 1

        # ===== Request 1: Read firmware version (addresses 19-23, 5 registers) =====
        version_chars = []
        try:
            req = ModbusRTU.read_holding_registers(slave_id, 19, 5)
            self.parent_window.ser.write(req)
            time.sleep(0.02)
            response = self.parent_window.ser.read(256)

            if len(response) >= 15:  # 3 (header) + 10 (data) + 2 (crc) = 15 bytes
                # Parse 5 registers starting from byte 3
                for i in range(5):
                    high_byte = response[3 + i*2]
                    low_byte = response[4 + i*2]
                    # Convert to ASCII characters
                    char1 = chr(high_byte) if 32 <= high_byte <= 126 else '?'
                    char2 = chr(low_byte) if 32 <= low_byte <= 126 else '?'
                    version_chars.append(char1 + char2)
            else:
                version_chars = ['??'] * 5
        except:
            version_chars = ['??'] * 5

        # Format version string: ABCD-1234-22 (insert '-' after positions 4 and 8)
        if len(version_chars) == 5:
            version_str = ''.join(version_chars)
            formatted_version = f"{version_str[0:4]}-{version_str[4:8]}-{version_str[8:10]}"
            self.lbl_firmware.setText(f"Firmware Version : {formatted_version}")
        else:
            self.lbl_firmware.setText("Firmware Version : ----/----/--")

        # ===== Request 2: Read device info part 1 (addresses 24-29, 6 registers) =====
        try:
            req = ModbusRTU.read_holding_registers(slave_id, 24, 6)
            self.parent_window.ser.write(req)
            time.sleep(0.02)
            response = self.parent_window.ser.read(256)

            if len(response) >= 15:  # 3 (header) + 12 (data) + 2 (crc) = 17 bytes
                # Parse registers: 24-29 (Speed Max, Speed Min, Speed Stop, Duty Max, Duty Min, Power)
                # Map to device_registers indices: 0, 1, 2, 4, 5, 3
                reg_map = {24: 0, 25: 1, 26: 2, 27: 4, 28: 5, 29: 3}

                for i in range(6):
                    addr = 24 + i
                    raw_value = (response[3 + i*2] << 8) | response[4 + i*2]

                    if addr in reg_map:
                        idx = reg_map[addr]
                        reg = self.device_registers[idx]
                        scaled_value = raw_value * reg["scale"]
                        self.data_labels[idx].setText(f"{scaled_value:.3f} {reg['unit']}")
        except:
            pass

        # ===== Request 3: Read device info part 2 (addresses 30-35, 6 registers) =====
        # Note: Address 33 (SV) is not used, but we read it anyway for efficiency
        try:
            req = ModbusRTU.read_holding_registers(slave_id, 30, 6)
            self.parent_window.ser.write(req)
            time.sleep(0.02)
            response = self.parent_window.ser.read(256)

            if len(response) >= 15:  # 3 (header) + 12 (data) + 2 (crc) = 17 bytes
                # Parse registers: 30-35 (OC, OV, UV, SV-skip, OT, unused-35)
                # Map to device_registers indices: 6, 7, 8, skip, 9, skip
                reg_map = {30: 6, 31: 7, 32: 8, 34: 9}  # Skip 33 and 35

                for i in range(6):
                    addr = 30 + i
                    raw_value = (response[3 + i*2] << 8) | response[4 + i*2]

                    if addr in reg_map:
                        idx = reg_map[addr]
                        reg = self.device_registers[idx]
                        scaled_value = raw_value * reg["scale"]
                        self.data_labels[idx].setText(f"{scaled_value:.3f} {reg['unit']}")
        except:
            pass

        # Update timestamp
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.lbl_last_update.setText(f"Last update: {now}")


class LoadSettingsDialog(QtWidgets.QDialog):
    """Dialog to select 03 and 04 definition files"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Load Definition Files")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)  # Increased height for 5 dropdowns

        # Unified memory for saved selections
        self.load_mem = LoadMemory.load()

        # Scan for .ddata files
        self.files_03 = []
        # 04 files categorized by type
        self.files_04_normal = []
        self.files_04_bypass = []
        self.files_04_inverter = []
        self.files_04_converter = []
        self.files_04_gsensor = []
        self._scan_ddata_files()

        # Build UI
        self._build_ui()

        # Load current selections from LoadSettings.dmem via LoadMemory
        self._load_current_selections()

    def _scan_ddata_files(self):
        """Scan ./setting for all .ddata files and use the same list for all combos."""
        try:
            setting_folder = Path('./setting')
            if not setting_folder.exists():
                return

            all_files = [str(p) for p in setting_folder.glob('*.ddata')]
            # Sort once by filename for a consistent user experience
            all_files.sort(key=lambda x: Path(x).name.lower())

            # Use the same full list for every selector (03 and all 04 modes)
            self.files_03 = list(all_files)
            self.files_04_normal = list(all_files)
            self.files_04_bypass = list(all_files)
            self.files_04_inverter = list(all_files)
            self.files_04_converter = list(all_files)
            self.files_04_gsensor = list(all_files)

        except Exception:
            pass

    def _build_ui(self):
        """Build dialog UI"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = QtWidgets.QLabel("Definition Files Setting")
        title.setStyleSheet(f"font-size:24px; font-weight:700; color:{Colors.TEXT_PRIMARY}; border:none; padding:10px 0px;")
        layout.addWidget(title)

        # Form layout
        form = QtWidgets.QFormLayout()
        form.setSpacing(10)
        form.setHorizontalSpacing(15)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)  # Right-align labels
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)

        # 03 file selector (combo only)
        lbl_03 = QtWidgets.QLabel("03 definition")
        lbl_03.setStyleSheet(f"color:{Colors.TEXT_PRIMARY}; font-weight:600; font-size:14px; border:none;")
        lbl_03.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.combo_03 = SearchableCombo()
        self.combo_03.setMinimumWidth(300)
        self.combo_03.addItem("(Not set)", None)
        for file in self.files_03:
            display_name = Path(file).stem  # Remove .ddata extension
            self.combo_03.addItem(display_name, file)
        self.combo_03.setStyleSheet(f"""
            QComboBox {{
                background:{Colors.BG_INPUT};
                color:{Colors.TEXT_PRIMARY};
                border:2px solid {Colors.BORDER_NORMAL};
                border-radius:6px;
                padding:8px;
                font-size:13px;
            }}
            QComboBox:hover {{
                border-color:{Colors.BORDER_FOCUS};
            }}
            QComboBox QAbstractItemView {{
                background:{Colors.BG_INPUT};
                color:{Colors.TEXT_PRIMARY};
                border:1px solid {Colors.BORDER_NORMAL};
                selection-background-color:{Colors.SOFT_YELLOW};
                selection-color:{Colors.MIDNIGHT_NAVY};
            }}
        """)
        form.addRow(lbl_03, self.combo_03)

        # 04 file selectors - 5 separate dropdowns for each type
        combo_style = f"""
            QComboBox {{
                background:{Colors.BG_INPUT};
                color:{Colors.TEXT_PRIMARY};
                border:2px solid {Colors.BORDER_NORMAL};
                border-radius:6px;
                padding:8px;
                font-size:13px;
            }}
            QComboBox:hover {{
                border-color:{Colors.BORDER_FOCUS};
            }}
            QComboBox QAbstractItemView {{
                background:{Colors.BG_INPUT};
                color:{Colors.TEXT_PRIMARY};
                border:1px solid {Colors.BORDER_NORMAL};
                selection-background-color:{Colors.SOFT_YELLOW};
                selection-color:{Colors.MIDNIGHT_NAVY};
            }}
        """

        # 04 Normal
        lbl_04_normal = QtWidgets.QLabel("04 (Normal)")
        lbl_04_normal.setStyleSheet(f"color:{Colors.TEXT_PRIMARY}; font-weight:600; font-size:14px; border:none;")
        lbl_04_normal.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.combo_04_normal = SearchableCombo()
        self.combo_04_normal.setMinimumWidth(300)
        self.combo_04_normal.addItem("(Not set)", None)
        for file in self.files_04_normal:
            display_name = Path(file).stem  # Remove .ddata extension
            self.combo_04_normal.addItem(display_name, file)
        self.combo_04_normal.setStyleSheet(combo_style)
        form.addRow(lbl_04_normal, self.combo_04_normal)

        # 04 Bypass
        lbl_04_bypass = QtWidgets.QLabel("04 (Bypass)")
        lbl_04_bypass.setStyleSheet(f"color:{Colors.TEXT_PRIMARY}; font-weight:600; font-size:14px; border:none;")
        lbl_04_bypass.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.combo_04_bypass = SearchableCombo()
        self.combo_04_bypass.setMinimumWidth(300)
        self.combo_04_bypass.addItem("(Not set)", None)
        for file in self.files_04_bypass:
            display_name = Path(file).stem  # Remove .ddata extension
            self.combo_04_bypass.addItem(display_name, file)
        self.combo_04_bypass.setStyleSheet(combo_style)
        form.addRow(lbl_04_bypass, self.combo_04_bypass)

        # 04 Inverter
        lbl_04_inverter = QtWidgets.QLabel("04 (Inverter)")
        lbl_04_inverter.setStyleSheet(f"color:{Colors.TEXT_PRIMARY}; font-weight:600; font-size:14px; border:none;")
        lbl_04_inverter.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.combo_04_inverter = SearchableCombo()
        self.combo_04_inverter.setMinimumWidth(300)
        self.combo_04_inverter.addItem("(Not set)", None)
        for file in self.files_04_inverter:
            display_name = Path(file).stem  # Remove .ddata extension
            self.combo_04_inverter.addItem(display_name, file)
        self.combo_04_inverter.setStyleSheet(combo_style)
        form.addRow(lbl_04_inverter, self.combo_04_inverter)

        # 04 Converter
        lbl_04_converter = QtWidgets.QLabel("04 (Converter)")
        lbl_04_converter.setStyleSheet(f"color:{Colors.TEXT_PRIMARY}; font-weight:600; font-size:14px; border:none;")
        lbl_04_converter.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.combo_04_converter = SearchableCombo()
        self.combo_04_converter.setMinimumWidth(300)
        self.combo_04_converter.addItem("(Not set)", None)
        for file in self.files_04_converter:
            display_name = Path(file).stem  # Remove .ddata extension
            self.combo_04_converter.addItem(display_name, file)
        self.combo_04_converter.setStyleSheet(combo_style)
        form.addRow(lbl_04_converter, self.combo_04_converter)

        # 04 Gsensor
        lbl_04_gsensor = QtWidgets.QLabel("04 (Gsensor)")
        lbl_04_gsensor.setStyleSheet(f"color:{Colors.TEXT_PRIMARY}; font-weight:600; font-size:14px; border:none;")
        lbl_04_gsensor.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.combo_04_gsensor = SearchableCombo()
        self.combo_04_gsensor.setMinimumWidth(300)
        self.combo_04_gsensor.addItem("(Not set)", None)
        for file in self.files_04_gsensor:
            display_name = Path(file).stem  # Remove .ddata extension
            self.combo_04_gsensor.addItem(display_name, file)
        self.combo_04_gsensor.setStyleSheet(combo_style)
        form.addRow(lbl_04_gsensor, self.combo_04_gsensor)

        layout.addLayout(form)

        # Spacer
        layout.addStretch()

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()

        # Info bar: show .dmem path and open folder
        info_layout = QtWidgets.QHBoxLayout()
        mem_path = Path('./setting/LoadSettings.dmem')
        self.lbl_info = QtWidgets.QLabel(f"Memory: {mem_path}")
        self.lbl_info.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-size:12px; border:none;")
        info_layout.addWidget(self.lbl_info)
        info_layout.addStretch()
        self.btn_open_folder = QtWidgets.QPushButton("Open Folder")
        self.btn_open_folder.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; font-weight:600; font-size:12px; padding:6px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        def _open_folder():
            try:
                folder = mem_path.parent.resolve()
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))
            except Exception:
                pass
        self.btn_open_folder.clicked.connect(_open_folder)
        info_layout.addWidget(self.btn_open_folder)
        layout.addLayout(info_layout)

        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:14px; padding:8px 20px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.BTN_DANGER_HOVER};}} "
            f"QPushButton:pressed{{background:{Colors.BTN_DANGER_BG};}}"
        )
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_apply = QtWidgets.QPushButton("Apply (Save & Load)")
        self.btn_apply.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:14px; padding:8px 20px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}"
        )
        self.btn_apply.clicked.connect(self._on_apply)
        btn_layout.addWidget(self.btn_apply)

        layout.addLayout(btn_layout)

        # Set dialog background
        self.setStyleSheet(f"QDialog{{background:{Colors.BG_PANEL};}}")

    def _load_current_selections(self):
        """Load current selections using LoadMemory (match by filename)."""
        try:
            mem = self.load_mem

            # Helper to set selection by filename
            def set_combo_by_filename(combo: QtWidgets.QComboBox, filename: str):
                if not filename:
                    # reset normal border
                    combo.setStyleSheet(combo.styleSheet().replace('border:2px solid red;', f'border:2px solid {Colors.BORDER_NORMAL};'))
                    return
                for i in range(1, combo.count()):  # skip (None)
                    data = combo.itemData(i)
                    if not data:
                        continue
                    if Path(data).name == filename:
                        # SearchableCombo requires this flag to allow programmatic selection
                        if hasattr(combo, "_allow_commit"):
                            combo._allow_commit = True
                        combo.setCurrentIndex(i)
                        if hasattr(combo, "_allow_commit"):
                            combo._allow_commit = False
                        # reset normal border on found
                        combo.setToolTip("")
                        combo.setStyleSheet(combo.styleSheet().replace('border:2px solid red;', f'border:2px solid {Colors.BORDER_NORMAL};'))
                        break
                else:
                    # not found: highlight red and set tooltip
                    combo.setCurrentIndex(0)
                    combo.setToolTip("file not found")
                    combo.setStyleSheet(combo.styleSheet() + " QComboBox{border:2px solid red;} ")

            # Preselect combos using saved memory
            set_combo_by_filename(self.combo_03, mem.file_03)
            set_combo_by_filename(self.combo_04_normal, mem.file_04.get("Normal", ""))
            set_combo_by_filename(self.combo_04_bypass, mem.file_04.get("Bypass", ""))
            set_combo_by_filename(self.combo_04_inverter, mem.file_04.get("Inverter", ""))
            set_combo_by_filename(self.combo_04_converter, mem.file_04.get("Converter", ""))
            set_combo_by_filename(self.combo_04_gsensor, mem.file_04.get("Gsensor", ""))
        except Exception:
            pass

    def _on_apply(self):
        """Persist selections to LoadMemory and accept dialog."""
        try:
            # Store only filenames to memory
            file_03 = ""
            if self.combo_03.currentIndex() != 0:
                sel = self.combo_03.currentData()
                file_03 = Path(sel).name if sel else ""

            file_04 = {
                "Normal": Path(self.combo_04_normal.currentData()).name if self.combo_04_normal.currentIndex() != 0 and self.combo_04_normal.currentData() else "",
                "Bypass": Path(self.combo_04_bypass.currentData()).name if self.combo_04_bypass.currentIndex() != 0 and self.combo_04_bypass.currentData() else "",
                "Inverter": Path(self.combo_04_inverter.currentData()).name if self.combo_04_inverter.currentIndex() != 0 and self.combo_04_inverter.currentData() else "",
                "Converter": Path(self.combo_04_converter.currentData()).name if self.combo_04_converter.currentIndex() != 0 and self.combo_04_converter.currentData() else "",
                "Gsensor": Path(self.combo_04_gsensor.currentData()).name if self.combo_04_gsensor.currentIndex() != 0 and self.combo_04_gsensor.currentData() else "",
            }

            self.load_mem.file_03 = file_03
            self.load_mem.file_04 = file_04
            self.load_mem.save()
        except Exception:
            pass
        self.accept()

    def get_selected_03_file(self):
        """Get selected 03 filename (not full path)."""
        if self.combo_03.currentIndex() == 0:
            return ""
        data = self.combo_03.currentData()
        return Path(data).name if data else ""

    def get_selected_04_files(self):
        """Get selected 04 filenames as a dictionary."""
        result = {}

        if self.combo_04_normal.currentIndex() != 0 and self.combo_04_normal.currentData():
            result["Normal"] = Path(self.combo_04_normal.currentData()).name
        else:
            result["Normal"] = ""

        if self.combo_04_bypass.currentIndex() != 0 and self.combo_04_bypass.currentData():
            result["Bypass"] = Path(self.combo_04_bypass.currentData()).name
        else:
            result["Bypass"] = ""

        if self.combo_04_inverter.currentIndex() != 0 and self.combo_04_inverter.currentData():
            result["Inverter"] = Path(self.combo_04_inverter.currentData()).name
        else:
            result["Inverter"] = ""

        if self.combo_04_converter.currentIndex() != 0 and self.combo_04_converter.currentData():
            result["Converter"] = Path(self.combo_04_converter.currentData()).name
        else:
            result["Converter"] = ""

        if self.combo_04_gsensor.currentIndex() != 0 and self.combo_04_gsensor.currentData():
            result["Gsensor"] = Path(self.combo_04_gsensor.currentData()).name
        else:
            result["Gsensor"] = ""

        return result


# ==================== Main Window ====================
class MainWindow(QtWidgets.QMainWindow):
    """Main application window"""

    def __init__(self, ui_scale: float = 1.0):
        super().__init__()
        self.setWindowTitle("Modbus RTU Controller")
        # Don't set initial size here - will be set based on screen resolution in main()

        # Initialize UI tokens for responsive sizing with provided scale
        self.tokens = UiTokens(ui_scale)

        self.serial_mgr = SerialManager(self)
        # Centralized Load Settings memory
        self.load_mem = LoadMemory.load()
        self.addr_items: List[str] = []  # ["000_name", ...]
        self.worker: Optional[PollWorker] = None
        self.plot_worker: Optional[PlotWorker] = None

        # Central timing state (ms)
        self.timeout_ms = DEFAULT_TIMEOUT_MS
        self.poll_interval_ms = DEFAULT_POLL_INTERVAL_MS

        # Plot data storage: 4 channels, each with (timestamps, values)
        self.plot_data = [
            {'time': [], 'value': []} for _ in range(4)
        ]
        self.plot_start_time = 0.0

        # Manual zoom state
        self.manual_zoom_active = False
        self.zoom_history = []  # Stack of (xlim, ylim) tuples for zoom out
        self.rect_selector = None  # Rectangle selector for drag-to-zoom

        # Channel enable/disable state
        self.plot_active = [True, True, True, True]  # CH1-CH4 enabled by default
        self.plotLabels: List[ClickableLabel] = []  # References to CH1-CH4 labels
        self.ch_actions: List[QtWidgets.QAction] = []  # Toolbar toggle actions for channel visibility

        # Cursor tool removed

        # Probe tool state
        self._probe_enabled = False
        self._probe_cid = None
        self._probe_artists = []
        self.probeValueLabels: List[QtWidgets.QLabel] = []  # Per-channel probe value display labels

        # Mode state for 0x04 register definition switching
        self.mode = "Normal"

        # Dictionary to store all 5 04def filenames (keyed by mode name)
        self.file_04_dict = {
            "Normal": "",
            "Bypass": "",
            "Inverter": "",
            "Converter": "",
            "Gsensor": ""
        }

        # Track currently loaded filenames for dialog display
        self.current_file_03 = ""
        self.current_file_04_by_mode = {
            "Normal": "",
            "Bypass": "",
            "Inverter": "",
            "Converter": "",
            "Gsensor": ""
        }

        # RR Mode state
        self.current_mode = "03"  # "03" for 03 Mode (monitoring), "RR" for RR Mode
        self.rr_worker: Optional[RRModeWorker] = None
        self.rr_dtbpt_parser: Optional[DtbptParser] = None
        self.rr_current_page = 0
        self.rr_data = [
            {'x': deque(maxlen=2000), 'y': deque(maxlen=2000)} for _ in range(4)  # 4 channels with x (data group index) and y (value)
        ]

        # RR mode performance optimizations
        self._rr_dirty = False
        self._rr_autoscale_counter = 0
        self.rr_window_width = 800  # Sliding window width in data points
        self.rr_plot_timer = QtCore.QTimer(self)
        self.rr_plot_timer.setInterval(33)  # 30 FPS (~33ms); set to 16 for ~60 FPS
        self.rr_plot_timer.timeout.connect(self._update_rr_plot)

        # Load default RR title file
        self._load_default_rr_titles()

        self._build_ui()
        self._auto_load_definitions()
        self._restore_last_mode()  # Restore last mode from file
        # Note: _auto_load_definitions() already loads 04 defs from dmem, no need to call _load_input_defs()
        self._update_input_titles()  # Update UI labels with custom titles
        self._refresh_ports()

    # ---------- UI Build ----------
    def _build_ui(self):
        """Build the user interface"""
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        main_layout = QtWidgets.QVBoxLayout(root)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # ========== TOP: UART Settings Panel ==========
        uart_panel = QtWidgets.QFrame()
        uart_panel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        uart_panel.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        uart_panel.setFixedHeight(60)
        uart_layout = QtWidgets.QHBoxLayout(uart_panel)
        uart_layout.setContentsMargins(12, 12, 12, 12)
        uart_layout.setSpacing(10)

        # Port
        lbl_port = QtWidgets.QLabel("COM Port")
        lbl_port.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        uart_layout.addWidget(lbl_port)
        self.cmbPort = SearchableCombo(half_width=False)
        self.cmbPort.setMinimumWidth(120)
        uart_layout.addWidget(self.cmbPort)

        # Baud
        lbl_baud = QtWidgets.QLabel("Baud")
        lbl_baud.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        uart_layout.addWidget(lbl_baud)
        self.cmbBaud = SearchableCombo(half_width=False)
        self.cmbBaud.setMinimumWidth(100)
        for b in ['1200','2400','4800','9600','19200','38400','57600','115200']:
            self.cmbBaud.addItem(b)
        self.cmbBaud.setCurrentText('9600')
        uart_layout.addWidget(self.cmbBaud)

        # Data bits
        lbl_databits = QtWidgets.QLabel("Data Bits")
        lbl_databits.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        uart_layout.addWidget(lbl_databits)
        self.cmbDataBits = SearchableCombo(half_width=False)
        self.cmbDataBits.setMinimumWidth(60)
        self.cmbDataBits.addItems(['7','8'])
        self.cmbDataBits.setCurrentText('8')
        uart_layout.addWidget(self.cmbDataBits)

        # Parity
        lbl_parity = QtWidgets.QLabel("Parity")
        lbl_parity.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        uart_layout.addWidget(lbl_parity)
        self.cmbParity = SearchableCombo(half_width=False)
        self.cmbParity.setMinimumWidth(100)
        self.cmbParity.addItems(['None (N)', 'Even (E)', 'Odd (O)'])
        self.cmbParity.setCurrentText('None (N)')
        uart_layout.addWidget(self.cmbParity)

        # Stop bits
        lbl_stopbits = QtWidgets.QLabel("Stop Bits")
        lbl_stopbits.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        uart_layout.addWidget(lbl_stopbits)
        self.cmbStopBits = SearchableCombo(half_width=False)
        self.cmbStopBits.setMinimumWidth(60)
        self.cmbStopBits.addItems(['1','2'])
        self.cmbStopBits.setCurrentText('1')
        uart_layout.addWidget(self.cmbStopBits)

        uart_layout.addStretch()

        # Load button
        self.btnLoad = QtWidgets.QPushButton("Load")
        self.btnLoad.setStyleSheet(f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}")
        self.btnLoad.clicked.connect(self.open_load_dialog)
        uart_layout.addWidget(self.btnLoad)

        # Refresh button
        self.btnRefreshPorts = QtWidgets.QPushButton("Refresh")
        self.btnRefreshPorts.setToolTip("Refresh COM ports")
        self.btnRefreshPorts.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        self.btnRefreshPorts.clicked.connect(self._refresh_ports)
        uart_layout.addWidget(self.btnRefreshPorts)

        # Connect button
        self.btnConnect = QtWidgets.QPushButton("Connect")
        self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}")
        self.btnConnect.clicked.connect(self._toggle_connection)
        uart_layout.addWidget(self.btnConnect)

        main_layout.addWidget(uart_panel)

        # ========== Motor Control Panel (RESPONSIVE) ==========
        motor_panel = QtWidgets.QFrame()
        motor_panel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        motor_panel.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        # Calculate required height: top_pad + input(40) + spacing(8) + button(40) + bottom_pad
        # Assuming pad() returns ~10-14px, total height = 10 + 40 + 8 + 40 + 10 = 108px minimum
        motor_panel.setMinimumSize(self.tokens.panel_minw(), 108)
        motor_panel.setMaximumHeight(108)
        motor_panel.setMaximumWidth(650)
        # Fixed height to prevent expansion
        motor_panel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

        motor_main_layout = QtWidgets.QVBoxLayout(motor_panel)
        # RESPONSIVE: Use token-based margins and spacing - reduced for compactness
        motor_main_layout.setContentsMargins(self.tokens.pad(), self.tokens.pad(), self.tokens.pad(), self.tokens.pad())
        motor_main_layout.setSpacing(8)  # Spacing between rows

        # Top row: input box and buttons
        motor_top_layout = QtWidgets.QHBoxLayout()
        motor_top_layout.setSpacing(self.tokens.gap())

        # Value input for motor control
        self.edMotorValue = QtWidgets.QLineEdit()
        self.edMotorValue.setText("0")
        self.edMotorValue.setValidator(QtGui.QIntValidator(0, 65535, self))
        # Reduced height for compactness
        self.edMotorValue.setMinimumHeight(40)
        self.edMotorValue.setMaximumHeight(40)
        self.edMotorValue.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        # RESPONSIVE: Use token-based font size
        self.edMotorValue.setStyleSheet(
            f"QLineEdit{{background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; "
            f"border:2px solid {Colors.BORDER_NORMAL}; padding:4px; border-radius:4px; font-size:{self.tokens.font_large()}px; font-weight:700;}} "
            f"QLineEdit:focus{{border-color:{Colors.BORDER_FOCUS};}}"
        )
        self.edMotorValue.returnPressed.connect(self._send_motor_value)
        motor_top_layout.addWidget(self.edMotorValue)

        # Send button (success style)
        self.btnMotorSend = QtWidgets.QPushButton("Send")
        # Reduced size for compactness
        self.btnMotorSend.setMinimumSize(self.tokens.btn_w(), 40)
        self.btnMotorSend.setMaximumHeight(40)
        self.btnMotorSend.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        # RESPONSIVE: Use token-based font size
        self.btnMotorSend.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:600; font-size:{self.tokens.font_xlarge()}px; padding:4px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}"
        )
        self.btnMotorSend.clicked.connect(self._send_motor_value)
        motor_top_layout.addWidget(self.btnMotorSend)

        # Stop button (danger style)
        self.btnMotorStop = QtWidgets.QPushButton("Stop")
        # Reduced size for compactness
        self.btnMotorStop.setMinimumSize(self.tokens.btn_w(), 40)
        self.btnMotorStop.setMaximumHeight(40)
        self.btnMotorStop.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        # RESPONSIVE: Use token-based font size
        self.btnMotorStop.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:600; font-size:{self.tokens.font_xlarge()}px; padding:4px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.BTN_DANGER_BG};}}"
        )
        self.btnMotorStop.clicked.connect(self._stop_motor)
        motor_top_layout.addWidget(self.btnMotorStop)

        motor_main_layout.addLayout(motor_top_layout)

        # Bottom row: Fan Info button
        motor_bottom_layout = QtWidgets.QHBoxLayout()
        motor_bottom_layout.setSpacing(self.tokens.gap())

        # Fan Info button
        self.btnFanInfo = QtWidgets.QPushButton("Fan Info.")
        self.btnFanInfo.setMinimumHeight(40)
        self.btnFanInfo.setMaximumHeight(40)
        self.btnFanInfo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.btnFanInfo.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; font-weight:600; font-size:{self.tokens.font_xlarge()}px; padding:4px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        self.btnFanInfo.clicked.connect(self.open_device_info_dialog)
        motor_bottom_layout.addWidget(self.btnFanInfo)

        motor_main_layout.addLayout(motor_bottom_layout)

        # ========== Read Addresses Panel ==========
        RWpanel = QtWidgets.QFrame()
        RWpanel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        RWpanel.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        # Set responsive panel size - allow flexible height
        RWpanel.setMinimumSize(550, 750)
        RWpanel.setMaximumWidth(650)
        RWpanel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        rv = QtWidgets.QVBoxLayout(RWpanel)
        # Internal padding for right frame
        rv.setContentsMargins(3, 1, 3, 1)
        # FIXED: Add spacing between register grid and input register frame to prevent overlap
        rv.setSpacing(8)  # 8px spacing prevents widgets from overlapping

        # Top row: Start button, ID, Timeout, Poll Interval in horizontal layout
        topRow = QtWidgets.QWidget()
        topLayout = QtWidgets.QHBoxLayout(topRow)
        topLayout.setSpacing(0)
        topLayout.setContentsMargins(6, 0, 6, 0)

        # Start/Stop Polling button
        self.btnPolling = QtWidgets.QPushButton("Start")
        self.btnPolling.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}")
        self.btnPolling.clicked.connect(self._toggle_polling)
        topLayout.addWidget(self.btnPolling)

        # Common widths
        LABEL_WIDTH = 80
        INPUT_WIDTH = 70

        # Slave ID (moved to UART panel after COM Port)
        lblSlave = QtWidgets.QLabel("ID")
        lblSlave.setFixedWidth(LABEL_WIDTH)
        lblSlave.setAlignment(QtCore.Qt.AlignCenter)
        lblSlave.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        self.edSlave = QtWidgets.QLineEdit("1")
        self.edSlave.setValidator(QtGui.QIntValidator(1, 247, self))
        self.edSlave.setFixedWidth(INPUT_WIDTH)
        self.edSlave.setStyleSheet(f"background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; border:2px solid {Colors.BORDER_NORMAL}; padding:4px; border-radius:4px;")
        # Insert into UART layout right after COM Port widgets
        uart_layout.insertWidget(2, lblSlave)
        uart_layout.insertWidget(3, self.edSlave)

        # Timeout and Poll defaults (ms) from centralized variables
        self.edTimeout = QtWidgets.QLineEdit(str(DEFAULT_TIMEOUT_MS))
        self.edPoll = QtWidgets.QLineEdit(str(DEFAULT_POLL_INTERVAL_MS))
        # Keep variables in sync with UI edits
        self.edTimeout.editingFinished.connect(self._on_timeout_changed)
        self.edPoll.editingFinished.connect(self._on_poll_changed)

        topLayout.addStretch()

        # Load button will be moved below the grid (bottom-left)

        rv.addWidget(topRow)

        # Register grid (10 rows) without scroll
        gridWidget = QtWidgets.QWidget()
        # FIXED: Set size policy to prevent excessive expansion that causes overlap
        gridWidget.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        grid = QtWidgets.QGridLayout(gridWidget)
        # Internal padding and spacing inside the register grid
        grid.setContentsMargins(1, 5, 1, 5)
        grid.setHorizontalSpacing(8)  # Increased from 4 to 8 for better column separation
        grid.setVerticalSpacing(7)  # Increased from 10 to 15 for taller grid
        # Column stretch ratio: address_list : read_value : enter_value = 8 : 6 : 6
        # Increased value and write box widths for better readability
        grid.setColumnStretch(0, 8)
        grid.setColumnStretch(1, 6)
        grid.setColumnStretch(2, 6)

        self.rowCombos: List[SearchableCombo] = []
        self.rowValues: List[QtWidgets.QLabel] = []
        self.rowEdits:  List[QtWidgets.QLineEdit] = []

        for i in range(10):
            r = i
            # No numeric label column; start with the address selector
            combo = SearchableCombo(half_width=False)
            combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            combo.setMinimumHeight(25)  # Match height with value and edit boxes
            combo.addItem("---")
            # Use same styling as COM port - no custom arrow styling
            grid.addWidget(combo, r, 0)
            self.rowCombos.append(combo)

            val = QtWidgets.QLabel("----")
            val.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            val.setMinimumHeight(25)  # Increased height for better readability
            val.setStyleSheet(f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; padding:6px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; font-weight:600; font-size:14px;")
            grid.addWidget(val, r, 1)
            self.rowValues.append(val)

            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText("Enter value (0-65535)")
            edit.setValidator(QtGui.QIntValidator(0, 65535, self))
            edit.setMinimumHeight(25)  # Increased height for better readability
            edit.setStyleSheet(f"QLineEdit{{background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; border:2px solid {Colors.BORDER_NORMAL}; padding:4px; border-radius:4px;}} QLineEdit:focus{{border-color:{Colors.BORDER_FOCUS};}}")
            edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            edit.returnPressed.connect(lambda idx=i: self._write_register(idx))
            grid.addWidget(edit, r, 2)
            self.rowEdits.append(edit)

        rv.addWidget(gridWidget)

        # Input Register Display (FC 0x04)
        inputRegFrame = QtWidgets.QFrame()
        inputRegFrame.setMinimumHeight(250)
        inputRegFrame.setMaximumHeight(400)
        inputRegFrame.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:2px solid {Colors.BORDER_PANEL}; border-radius:6px;}}")

        # Create grid layout with 6 rows | 2 columns (12 registers total)
        inputGrid = QtWidgets.QGridLayout(inputRegFrame)
        inputGrid.setContentsMargins(3, 3, 3, 3)
        inputGrid.setHorizontalSpacing(8)
        inputGrid.setVerticalSpacing(2)

        # Add 8 input registers (4 rows | 2 columns)
        self.inputRegLabels: List[QtWidgets.QLabel] = []  # Store title labels
        self.inputRegValues: List[QtWidgets.QLabel] = []
        for i in range(8):
            row = i // 2  # 0,0,1,1,2,2,3,3
            col = i % 2   # 0,1,0,1,0,1,0,1

            # Create horizontal container for label + value
            container = QtWidgets.QWidget()
            hbox = QtWidgets.QHBoxLayout(container)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.setSpacing(8)

            # Label "INx" (will be updated from definition file)
            lbl = QtWidgets.QLabel(f"IN{i}")
            lbl.setFixedWidth(130)  # Increased width to accommodate custom titles
            lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            lbl.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700; font-size:14px; padding:4px;")
            hbox.addWidget(lbl)
            self.inputRegLabels.append(lbl)  # Store for later title updates

            # Value display
            val = QtWidgets.QLabel("----")
            val.setAlignment(QtCore.Qt.AlignCenter)
            val.setStyleSheet(
                f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; "
                f"padding:8px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; "
                f"font-weight:600; font-size:16px;"
            )
            hbox.addWidget(val)
            self.inputRegValues.append(val)

            # Add to grid
            inputGrid.addWidget(container, row, col)

        # Add 4 additional registers (IN8-IN11) for addresses 0x08-0x09 and 0x0E-0x0F
        # Row 4: IN8 (0x08), IN9 (0x09)
        # Row 5: IN10 (0x0E), IN11 (0x0F)
        for i in range(8, 12):
            row = 4 + (i - 8) // 2  # 4,4,5,5
            col = (i - 8) % 2       # 0,1,0,1

            # Create horizontal container for label + value
            container = QtWidgets.QWidget()
            hbox = QtWidgets.QHBoxLayout(container)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.setSpacing(8)

            # Label "INx"
            lbl = QtWidgets.QLabel(f"IN{i}")
            lbl.setFixedWidth(130)
            lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            lbl.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700; font-size:14px; padding:4px;")
            hbox.addWidget(lbl)
            self.inputRegLabels.append(lbl)

            # Value display
            val = QtWidgets.QLabel("----")
            val.setAlignment(QtCore.Qt.AlignCenter)
            val.setStyleSheet(
                f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; "
                f"padding:8px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; "
                f"font-weight:600; font-size:16px;"
            )
            hbox.addWidget(val)
            self.inputRegValues.append(val)

            # Add to grid
            inputGrid.addWidget(container, row, col)

        rv.addWidget(inputRegFrame)

        # Status bar
        self.status = QtWidgets.QStatusBar()
        self.setStatusBar(self.status)
        self._set_status("Ready")

        # region === RD Panel (Special Command Buttons - RESPONSIVE) ===
        RDpanel = QtWidgets.QFrame()
        RDpanel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        RDpanel.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        # RESPONSIVE: Use token-based minimum height instead of fixed, allow slight vertical expansion
        RDpanel.setMinimumHeight(self.tokens.panel_h_control())
        RDpanel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)

        rd_layout = QtWidgets.QGridLayout(RDpanel)
        # RESPONSIVE: Use token-based margins and spacing that scale with display
        rd_layout.setContentsMargins(int(10 * self.tokens.s), self.tokens.pad()//2, int(50 * self.tokens.s), self.tokens.pad()//2)
        rd_layout.setHorizontalSpacing(int(15 * self.tokens.s))
        rd_layout.setVerticalSpacing(int(8 * self.tokens.s))

        # Row 0, Col 0: Normal indicator text (changes color when active)
        self.lblNormalLight = QtWidgets.QLabel("Normal")
        self.lblNormalLight.setAlignment(QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter)
        self.lblNormalLight.setStyleSheet(
            f"QLabel{{color:{Colors.BG_INPUT}; "
            f"font-weight:700; font-size:{self.tokens.font_large()}px; padding:0px; border:none;}}"
        )
        rd_layout.addWidget(self.lblNormalLight, 0, 0)

        # Row 0, Col 1: Normal button
        self.btnNormal = QtWidgets.QPushButton("Normal")
        # RESPONSIVE: Use token-based minimum width instead of fixed, allow expansion
        self.btnNormal.setMinimumWidth(self.tokens.btn_w())
        self.btnNormal.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        # RESPONSIVE: Use token-based font size
        self.btnNormal.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:{self.tokens.font_medium()}px; padding:3px 3px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        self.btnNormal.clicked.connect(lambda: self._send_rd_command("014600070001020000", "Normal"))
        rd_layout.addWidget(self.btnNormal, 0, 1)

        # Row 0, Col 2: List combobox
        self.rdCombo = SearchableCombo(half_width=False)
        self.rdCombo.addItems(["Inverter", "Converter", "Gsensor"])
        # RESPONSIVE: Use token-based font sizes
        self.rdCombo.setStyleSheet(f"""
            QComboBox {{
                font-size: {self.tokens.font_medium()}px;
                font-weight: 600;
                padding: 3px;
            }}
            QComboBox QAbstractItemView {{
                font-size: {self.tokens.font_medium()}px;
            }}
        """)
        # RESPONSIVE: Use token-based minimum width instead of fixed, allow expansion
        self.rdCombo.setMinimumWidth(self.tokens.combo_w())
        self.rdCombo.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        rd_layout.addWidget(self.rdCombo, 0, 2)

        # Row 1, Col 0: Bypass indicator text (changes color when active)
        self.lblBypassLight = QtWidgets.QLabel("Bypass")
        self.lblBypassLight.setAlignment(QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter)
        self.lblBypassLight.setStyleSheet(
            f"QLabel{{color:{Colors.BG_INPUT}; "
            f"font-weight:700; font-size:{self.tokens.font_large()}px; padding:0px; border:none;}}"
        )
        rd_layout.addWidget(self.lblBypassLight, 1, 0)

        # Row 1, Col 1: Bypass button
        self.btnBypass = QtWidgets.QPushButton("Bypass")
        # RESPONSIVE: Use token-based minimum width instead of fixed, allow expansion
        self.btnBypass.setMinimumWidth(self.tokens.btn_w())
        self.btnBypass.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        # RESPONSIVE: Use token-based font size
        self.btnBypass.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:{self.tokens.font_medium()}px; padding:5px 5px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        self.btnBypass.clicked.connect(lambda: self._send_rd_command("014600070001022308", "Bypass"))
        rd_layout.addWidget(self.btnBypass, 1, 1)

        # Row 1, Col 2: Switch button
        self.btnSwitch = QtWidgets.QPushButton("Switch")
        # RESPONSIVE: Use token-based minimum width instead of fixed, allow expansion
        self.btnSwitch.setMinimumWidth(self.tokens.btn_w())
        self.btnSwitch.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        # RESPONSIVE: Use token-based font size
        self.btnSwitch.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:{self.tokens.font_medium()}px; padding:5px 5px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        self.btnSwitch.clicked.connect(self._send_switch_command)
        rd_layout.addWidget(self.btnSwitch, 1, 2)

        # endregion

        # region === Reset Panel (Special Reset Buttons - RESPONSIVE) ===
        ResetPanel = QtWidgets.QFrame()
        ResetPanel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        ResetPanel.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        # RESPONSIVE: Increased minimum HEIGHT to prevent vertical text cutoff
        # Height calculation: 2 buttons + padding + spacing + borders
        # Base height 110px (was 80px) ensures both button texts display fully vertically
        ResetPanel.setMinimumSize(int(200 * self.tokens.s), int(80 * self.tokens.s))
        # Allow both horizontal and vertical expansion
        ResetPanel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)

        reset_layout = QtWidgets.QVBoxLayout(ResetPanel)
        # RESPONSIVE: Use token-based margins and spacing
        reset_layout.setContentsMargins(self.tokens.pad(), self.tokens.pad(), self.tokens.pad(), self.tokens.pad())
        reset_layout.setSpacing(self.tokens.gap())

        # Reset button
        self.btnReset = QtWidgets.QPushButton("Reset")
        # RESPONSIVE: Allow button to expand within the panel
        self.btnReset.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        # Set minimum height to ensure text displays without vertical cutoff
        self.btnReset.setMinimumHeight(int(20 * self.tokens.s))
        # RESPONSIVE: Use smaller font size for more compact appearance
        self.btnReset.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:{self.tokens.font_normal()}px; padding:1px 10px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        self.btnReset.clicked.connect(lambda: self._send_reset_command("010601040001", "Reset"))
        reset_layout.addWidget(self.btnReset)

        # Reset Def button
        self.btnResetDef = QtWidgets.QPushButton("Reset Def")
        # RESPONSIVE: Allow button to expand within the panel
        self.btnResetDef.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        # Set minimum height to ensure text displays without vertical cutoff
        self.btnResetDef.setMinimumHeight(int(20 * self.tokens.s))
        # RESPONSIVE: Use smaller font size for more compact appearance
        self.btnResetDef.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:{self.tokens.font_normal()}px; padding:1px 10px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        self.btnResetDef.clicked.connect(lambda: self._send_reset_command("010601040002", "Reset Def"))
        reset_layout.addWidget(self.btnResetDef)
        # endregion

        # Plot panel
        plot_panel = QtWidgets.QFrame()
        plot_panel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        plot_panel.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        # Allow flexible height to adapt to screen size
        plot_panel.setMinimumHeight(600)
        plot_panel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        pv = QtWidgets.QVBoxLayout(plot_panel)
        pv.setContentsMargins(2, 2, 2, 2)
        pv.setSpacing(1)

        # Address selection: 4 SearchableCombo boxes in a single row
        addrWidget = QtWidgets.QWidget()
        addrLayout = QtWidgets.QGridLayout(addrWidget)
        # addrLayout.setSpacing(2)
        addrLayout.setContentsMargins(0, 0, 0, 0)
        addrLayout.setHorizontalSpacing(4)
        addrLayout.setVerticalSpacing(1)



        self.plotCombos: List[SearchableCombo] = []
        channel_colors = [Colors.BENIUKON, Colors.MINT_GLOW, Colors.SOFT_YELLOW, Colors.ROSE_CORAL]
        for i in range(4):
            lbl = ClickableLabel(f"Ch{i+1}")
            lbl.setStyleSheet(f"color:{channel_colors[i]}; font-weight:700; border:2px solid {channel_colors[i]}; border-radius:4px; padding:4px;")
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            lbl.setFixedWidth(40)
            lbl.clicked.connect(lambda idx=i: self._toggle_plot_channel(idx))
            self.plotLabels.append(lbl)

            combo = SearchableCombo(half_width=False)
            combo.addItem("---")
            combo.setStyleSheet(f"font-size:12px; font-weight:500; border:2px solid {channel_colors[i]};")
            # Fit four label+combo pairs within the fixed panel width
            # combo.setFixedWidth(160)
            combo.setFixedHeight(35)

            # Place all channels on the same row
            row = 0
            col = i * 2  # label at even col, combo at odd col
            addrLayout.addWidget(lbl, row, col)
            addrLayout.addWidget(combo, row, col + 1)
            self.plotCombos.append(combo)

            # Add probe value label below each channel's combobox
            probe_val = QtWidgets.QLabel("---")
            probe_val.setAlignment(QtCore.Qt.AlignCenter)
            probe_val.setFixedHeight(30)
            probe_val.setStyleSheet(
                f"color:{channel_colors[i]}; font-weight:700; font-size:14px; padding:4px; margin:0px; "
                f"border:1px solid {channel_colors[i]}; border-radius:4px; background:{Colors.BG_INPUT};"
            )
            addrLayout.addWidget(probe_val, 1, col, 1, 2)
            self.probeValueLabels.append(probe_val)

        pv.addWidget(addrWidget)

        # Apply initial channel styles
        for i in range(4):
            self._apply_plot_channel_style(i)

        # RR Mode controls row
        rr_control_widget = QtWidgets.QWidget()
        rr_control_layout = QtWidgets.QHBoxLayout(rr_control_widget)
        rr_control_layout.setContentsMargins(0, 5, 0, 5)
        rr_control_layout.setSpacing(10)

        # Mode switch button (03 Mode / RR Mode)
        self.btnModeSwitch = QtWidgets.QPushButton("03")
        self.btnModeSwitch.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:700; font-size:16px; padding:8px 20px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        self.btnModeSwitch.setFixedHeight(35)
        self.btnModeSwitch.setFixedWidth(80)
        self.btnModeSwitch.clicked.connect(self._toggle_mode)
        rr_control_layout.addWidget(self.btnModeSwitch)

        # RR Mode page selector label
        lbl_page = QtWidgets.QLabel("Page:")
        lbl_page.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:600; font-size:14px;")
        rr_control_layout.addWidget(lbl_page)

        # RR Mode page selector (0-12)
        self.cmbRRPage = SearchableCombo(half_width=False)
        self.cmbRRPage.setMinimumWidth(80)
        self.cmbRRPage.setFixedHeight(35)
        for i in range(13):  # Pages 0-12
            self.cmbRRPage.addItem(str(i))
        self.cmbRRPage.setCurrentText("0")
        self.cmbRRPage.currentIndexChanged.connect(self._on_rr_page_changed)
        rr_control_layout.addWidget(self.cmbRRPage)

        # Load .dtbpt button
        self.btnLoadDtbpt = QtWidgets.QPushButton("Load .dtbpt")
        self.btnLoadDtbpt.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:14px; padding:8px 16px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        self.btnLoadDtbpt.setFixedHeight(35)
        self.btnLoadDtbpt.clicked.connect(self._load_dtbpt_file)
        rr_control_layout.addWidget(self.btnLoadDtbpt)

        # Initially disable RR controls (enabled only in RR Mode)
        self.cmbRRPage.setEnabled(False)
        self.btnLoadDtbpt.setEnabled(False)

        rr_control_layout.addStretch()
        pv.addWidget(rr_control_widget)

        # Draw button
        self.btnDraw = QtWidgets.QPushButton("Draw")
        self.btnDraw.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}")
        # Keep the button compact instead of stretching across the panel
        self.btnDraw.setFixedHeight(40)
        self.btnDraw.setFixedWidth(250)
        self.btnDraw.clicked.connect(self._toggle_plotting)
        pv.addWidget(self.btnDraw, alignment=QtCore.Qt.AlignHCenter)

        # Matplotlib canvas
        self.plot_figure = Figure(figsize=(8, 6), dpi=100, facecolor=Colors.BG_PANEL)
        self.plot_canvas = FigureCanvas(self.plot_figure)
        self.plot_canvas.setStyleSheet(f"background:{Colors.BG_PANEL};")
        self.plot_ax = self.plot_figure.add_subplot(111, facecolor=Colors.COOL_GRAY)
        # self.plot_ax.set_xlabel('Time (s)', color=Colors.TEXT_PRIMARY)
        # self.plot_ax.set_ylabel('Value', color=Colors.TEXT_PRIMARY)
        self.plot_ax.tick_params(colors=Colors.TEXT_PRIMARY)
        for spine in self.plot_ax.spines.values():
            spine.set_color(Colors.BORDER_NORMAL)
        self.plot_ax.grid(True, alpha=0.3, color=Colors.TEXT_LABEL)
        self.plot_figure.tight_layout(pad=1.0)

        # Line objects for 4 channels
        self.plot_lines = []
        colors = [Colors.BENIUKON, Colors.MINT_GLOW, Colors.SOFT_YELLOW, Colors.ROSE_CORAL]
        for i, color in enumerate(colors):
            line, = self.plot_ax.plot([], [], label=f'Ch{i+1}', color=color, linewidth=1.5)
            line.set_antialiased(False)  # Disable antialiasing for better performance in RR mode
            self.plot_lines.append(line)
        self.plot_ax.legend(loc='upper left', facecolor=Colors.BG_PANEL, edgecolor=Colors.BORDER_NORMAL, labelcolor=Colors.TEXT_PRIMARY)

        # Add navigation toolbar below the plot
        self.plot_toolbar = NavigationToolbar2QT(self.plot_canvas, plot_panel)
        self.plot_toolbar.setStyleSheet(f"""
            QToolBar {{
                background: {Colors.BG_PANEL};
                border: 1px solid {Colors.BORDER_NORMAL};
                border-radius: 4px;
                spacing: 3px;
                padding: 2px;
            }}
            QToolButton {{
                background: {Colors.BG_INPUT};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_NORMAL};
                border-radius: 3px;
                padding: 3px;
                margin: 1px;
            }}
            QToolButton:hover {{
                background: {Colors.AKAKUCHIBA};
                border-color: {Colors.BORDER_FOCUS};
            }}
            QToolButton:pressed {{
                background: {Colors.DEEP_BLUE};
            }}
        """)

        pv.addWidget(self.plot_canvas)
        pv.addWidget(self.plot_toolbar)

        # Filter toolbar buttons: keep only Home, Pan, Zoom, Customize, and Save
        self._filter_toolbar_buttons()

        # FIXED: Override Home button to auto-fit current data instead of restoring empty view
        try:
            if hasattr(self, "plot_toolbar") and self.plot_toolbar is not None:
                # Find the Home action in the toolbar
                for action in self.plot_toolbar.actions():
                    if action.text() == 'Home':
                        # Disconnect default behavior
                        try:
                            action.triggered.disconnect()
                        except TypeError:
                            pass  # No connections to disconnect
                        # Connect our custom behavior
                        action.triggered.connect(self._on_home_clicked)
                        break
        except Exception:
            pass

        # Cursor tool removed

        # Add probe tool button to toolbar
        self._add_probe_button()

        # Add channel toggle buttons to toolbar
        self._add_channel_toggle_buttons()

        # Move Save button and add CSV button after channel toggles
        self._reorder_save_buttons()
        self._add_save_data_button()

        # Connect interactive zoom events after canvas creation
        self._connect_plot_events()

        # Add all panels to main layout
        main_layout.addWidget(uart_panel)

        # Create left column with Motor Control and Read Addresses panels
        left_column = QtWidgets.QVBoxLayout()
        left_column.setSpacing(8)
        left_column.addWidget(motor_panel)  # Motor Control Panel on top
        left_column.addWidget(RWpanel)  # Read Addresses Panel on bottom

        # Create top row for RD and Reset panels (above plot panel)
        top_control_row = QtWidgets.QHBoxLayout()
        top_control_row.setSpacing(8)
        top_control_row.addWidget(RDpanel)      # RD Panel (left)
        top_control_row.addWidget(ResetPanel)   # Reset Panel (right)

        # Create right column with top control row and plot panel
        right_column = QtWidgets.QVBoxLayout()
        right_column.setSpacing(8)
        right_column.addLayout(top_control_row)  # Top control row (RD + Reset)
        right_column.addWidget(plot_panel)       # Plot panel below

        # Create bottom layout with left column and right column
        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.setSpacing(8)
        bottom_layout.addLayout(left_column)  # Left column (motor + read addresses)
        bottom_layout.addLayout(right_column)  # Right column (controls + plot)

        main_layout.addLayout(bottom_layout)

    # ---------- Toolbar Filtering ----------
    def _filter_toolbar_buttons(self):
        """Filter toolbar to show only Home, Pan, Zoom, and Save buttons"""
        # Matplotlib NavigationToolbar2QT action texts to keep
        keep_actions = ['Home', 'Pan', 'Zoom', 'Save']

        # Get all actions from the toolbar
        all_actions = self.plot_toolbar.actions()

        # Remove unwanted actions
        for action in all_actions:
            if action.isSeparator():
                continue  # Keep separators
            action_text = action.text().replace('&', '')  # Remove mnemonic
            if action_text not in keep_actions:
                self.plot_toolbar.removeAction(action)

    # ---------- Probe Tool ----------
    def _add_probe_button(self):
        """Add Probe tool button to toolbar"""
        # Insert before the last action (coordinate display)
        existing_actions = self.plot_toolbar.actions()

        # Create probe toggle action
        self._probe_action = QtWidgets.QAction("PB", self.plot_toolbar)
        self._probe_action.setCheckable(True)
        self._probe_action.setChecked(False)
        self._probe_action.setToolTip("Click to probe all active channel values at a time point")
        self._probe_action.toggled.connect(self._toggle_probe_mode)

        # Insert before last action (coordinate display)
        if existing_actions:
            self.plot_toolbar.insertAction(existing_actions[-1], self._probe_action)
        else:
            self.plot_toolbar.addAction(self._probe_action)

        # Ensure the toolbar shows full text label with bold font and initialize style
        self._ensure_action_text_only(self._probe_action)
        self._update_toggle_action_style(self._probe_action, active_color=Colors.ROSE_CORAL)

    def _set_probe_label(self, idx: int, text: str, active: bool = True):
        """Update one channel's probe display text and color."""
        if 0 <= idx < len(self.probeValueLabels):
            lbl = self.probeValueLabels[idx]
            colors = [Colors.BENIUKON, Colors.MINT_GLOW, Colors.SOFT_YELLOW, Colors.ROSE_CORAL]
            color = colors[idx] if active else "#808A98"
            lbl.setText(text)
            lbl.setStyleSheet(
                f"color:{color}; font-weight:700; font-size:14px; padding:4px; margin:0px; "
                f"border:1px solid {color}; border-radius:4px; background:{Colors.BG_INPUT};"
            )

    def _clear_probe_labels(self):
        """Reset all probe labels."""
        for i in range(4):
            self._set_probe_label(i, "-", active=True)

    def _toggle_probe_mode(self, on: bool):
        """Toggle probe mode on/off"""
        self._probe_enabled = on
        if on:
            # Connect click event
            self._probe_cid = self.plot_canvas.mpl_connect('button_press_event', self._on_probe_click)
            self._set_status("Probe tool enabled - Click on plot to sample channel values")
        else:
            # Disconnect click event
            if self._probe_cid is not None:
                self.plot_canvas.mpl_disconnect(self._probe_cid)
                self._probe_cid = None
            # Clear any existing probe graphics
            self._clear_probe_artists()
            # Clear probe value labels
            self._clear_probe_labels()
            self._set_status("Probe tool disabled")

        # Update visual style for the toolbar button based on state
        self._update_toggle_action_style(self._probe_action, active_color=Colors.ROSE_CORAL)

    def _clear_probe_artists(self):
        """Remove all probe graphics from the plot"""
        for artist in self._probe_artists:
            artist.remove()
        self._probe_artists.clear()
        self.plot_canvas.draw_idle()

    def _nearest_index(self, arr, x):
        """Find index of nearest value in sorted array using bisect"""
        if not arr:
            return None
        idx = bisect.bisect_left(arr, x)
        if idx == 0:
            return 0
        if idx == len(arr):
            return len(arr) - 1
        # Check which is closer: arr[idx-1] or arr[idx]
        if abs(arr[idx - 1] - x) < abs(arr[idx] - x):
            return idx - 1
        return idx

    def _on_probe_click(self, event):
        """Handle click event to probe channel values"""
        if not self._probe_enabled:
            return
        if event.inaxes != self.plot_ax:
            return
        if event.button != 1:  # Only left-click
            return

        # Get clicked X position
        x_probe = event.xdata

        # Clear previous probe
        self._clear_probe_artists()

        # Vertical guide line
        vline = self.plot_ax.axvline(x_probe, color=Colors.ROSE_CORAL, linewidth=2, linestyle='-', alpha=0.8)
        self._probe_artists.append(vline)

        # Sample each active channel
        channel_colors = [Colors.BENIUKON, Colors.MINT_GLOW, Colors.SOFT_YELLOW, Colors.ROSE_CORAL]

        # Determine which data source to use based on current mode
        if self.current_mode == "RR":
            # RR mode: x is data group index, display as "Probe @ Index {x}"
            status_parts = [f"Probe @ Index {x_probe:.1f}"]
        else:
            # 03 mode: x is time in seconds
            status_parts = [f"Probe @ {x_probe:.3f}s"]

        for i in range(4):
            # Check if channel is active (enabled for plotting)
            if not self.plot_active[i]:
                self._set_probe_label(i, "OFF", active=False)
                continue

            # Select data source based on current mode
            if self.current_mode == "RR":
                x_data = self.rr_data[i]['x']
                y_data = self.rr_data[i]['y']
            else:
                x_data = self.plot_data[i]['time']
                y_data = self.plot_data[i]['value']

            if not x_data:
                status_parts.append(f"CH{i+1}=N/A")
                self._set_probe_label(i, "N/A", active=False)
                continue

            # Find nearest index
            idx = self._nearest_index(x_data, x_probe)
            if idx is None:
                status_parts.append(f"CH{i+1}=N/A")
                self._set_probe_label(i, "N/A", active=False)
                continue

            # Get the value at that index
            y_val = y_data[idx]
            x_val = x_data[idx]

            # Draw circle marker
            marker = self.plot_ax.plot(x_val, y_val, 'o', color=channel_colors[i],
                                      markersize=10, markeredgewidth=2,
                                      markeredgecolor=Colors.CREAM_TINT)[0]
            self._probe_artists.append(marker)

            # Add to status message
            status_parts.append(f"CH{i+1}={y_val:5d}")

            # Update per-channel probe label
            self._set_probe_label(i, f"{y_val: d}", active=True)

        # Update status bar
        self._set_status(", ".join(status_parts))

        # Redraw
        self.plot_canvas.draw_idle()

    # ---------- Save Data ----------
    def _reorder_save_buttons(self):
        """Move Save (image) button to after channel toggles"""
        # Find the Save action
        existing_actions = self.plot_toolbar.actions()
        save_action = None

        for action in existing_actions:
            if action.text() == 'Save':
                save_action = action
                break

        if save_action:
            # Remove Save action from its current position
            self.plot_toolbar.removeAction(save_action)

            # Insert before last action (coordinate display)
            if existing_actions:
                self.plot_toolbar.insertAction(existing_actions[-1], save_action)
            else:
                self.plot_toolbar.addAction(save_action)

    def _add_save_data_button(self):
        """Add Save Data button to toolbar"""
        # Get all existing actions
        existing_actions = self.plot_toolbar.actions()

        # Create save data action
        self._save_data_action = QtWidgets.QAction("CSV", self.plot_toolbar)
        self._save_data_action.setCheckable(False)
        self._save_data_action.setToolTip("Export plot data to CSV file")
        self._save_data_action.triggered.connect(self._save_plot_data)

        # Find the Save action and insert CSV button right after it
        save_action_found = False
        for i, action in enumerate(existing_actions):
            if action.text() == 'Save':
                # Insert after the Save action
                if i + 1 < len(existing_actions):
                    self.plot_toolbar.insertAction(existing_actions[i + 1], self._save_data_action)
                else:
                    self.plot_toolbar.addAction(self._save_data_action)
                save_action_found = True
                break

        # Fallback: if Save button not found, insert before last action (coordinate display)
        if not save_action_found:
            if existing_actions:
                self.plot_toolbar.insertAction(existing_actions[-1], self._save_data_action)
            else:
                self.plot_toolbar.addAction(self._save_data_action)

        # Ensure the toolbar shows full text label with bold font
        self._ensure_action_text_only(self._save_data_action)

    def _save_plot_data(self):
        """Save plot data to CSV file"""
        try:
            # Check if there's any data to save
            has_data = False
            for i in range(4):
                if len(self.plot_data[i]['time']) > 0:
                    has_data = True
                    break

            if not has_data:
                QtWidgets.QMessageBox.warning(self, "No Data", "No plot data to save.")
                return

            # Open file dialog
            file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Save Plot Data",
                "",
                "CSV Files (*.csv);;All Files (*)"
            )

            if not file_path:
                return  # User canceled

            # Ensure .csv extension
            if not file_path.lower().endswith('.csv'):
                file_path += '.csv'

            # Determine maximum data length
            max_len = max(len(self.plot_data[i]['time']) for i in range(4))

            # Write CSV file
            import csv
            with open(file_path, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)

                # Write header
                header = ['Time (s)']
                for i in range(4):
                    if self.plot_active[i] and len(self.plot_data[i]['time']) > 0:
                        header.append(f'CH{i+1}')
                writer.writerow(header)

                # Write data rows
                for row_idx in range(max_len):
                    row = []
                    # Use time from first available channel
                    time_written = False
                    for i in range(4):
                        if not time_written and row_idx < len(self.plot_data[i]['time']):
                            row.append(f"{self.plot_data[i]['time'][row_idx]:.3f}")
                            time_written = True

                    if not time_written:
                        row.append('')  # Empty time if no data

                    # Write channel values
                    for i in range(4):
                        if self.plot_active[i] and len(self.plot_data[i]['time']) > 0:
                            if row_idx < len(self.plot_data[i]['value']):
                                row.append(str(self.plot_data[i]['value'][row_idx]))
                            else:
                                row.append('')  # Empty if no data for this channel

                    writer.writerow(row)

            QtWidgets.QMessageBox.information(self, "Success", f"Plot data saved to:\n{file_path}")
            self._set_status(f"Plot data saved to {file_path}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to save plot data:\n{str(e)}")
            self._set_status(f"Failed to save plot data: {e}")

    # ---------- Channel Visibility Toggle ----------
    def _add_channel_toggle_buttons(self):
        """Add CH1-CH4 toggle buttons to the navigation toolbar"""
        # Get all existing actions (to insert before coordinate display)
        existing_actions = self.plot_toolbar.actions()

        # Insert separator before the last action (coordinate display)
        if existing_actions:
            self.plot_toolbar.insertSeparator(existing_actions[-1])

        # Channel colors matching the plot lines
        colors = [Colors.BENIUKON, Colors.MINT_GLOW, Colors.SOFT_YELLOW, Colors.ROSE_CORAL]

        # Create toggle actions for each channel and insert before the last action
        for i in range(4):
            action = QtWidgets.QAction(f"CH{i+1}", self.plot_toolbar)
            action.setCheckable(True)
            action.setChecked(True)  # All visible by default
            action.toggled.connect(lambda checked, idx=i: self._on_channel_toggle(idx, checked))

            # Style the action button with channel color and bold font
            action.setToolTip(f"Toggle CH{i+1} visibility")

            # Store color as property for later use
            action.setProperty("channel_color", colors[i])
            action.setProperty("channel_index", i)

            # Insert before last action (coordinate display)
            if existing_actions:
                self.plot_toolbar.insertAction(existing_actions[-1], action)
            else:
                self.plot_toolbar.addAction(action)

            self.ch_actions.append(action)

        # Apply initial styling to all channel buttons
        self._update_channel_button_styles()

    def _on_channel_toggle(self, idx: int, checked: bool):
        """Handle channel visibility toggle from toolbar"""
        # Set line visibility
        self.plot_lines[idx].set_visible(checked)

        # Update button styling
        self._update_channel_button_styles()

        # Update probe label state when toggling channel visibility
        if checked:
            self._set_probe_label(idx, "-", active=True)
        else:
            self._set_probe_label(idx, "OFF", active=False)

        # Rebuild legend with only visible channels
        handles = [ln for ln in self.plot_lines if ln.get_visible()]
        labels = [f"Ch{i+1}" for i, ln in enumerate(self.plot_lines) if ln.get_visible()]

        # Remove old legend if exists
        if self.plot_ax.legend_:
            self.plot_ax.legend_.remove()

        # Create new legend with only visible channels
        if handles:  # Only create legend if there are visible channels
            self.plot_ax.legend(handles, labels, loc='upper left',
                              facecolor=Colors.BG_PANEL,
                              edgecolor=Colors.BORDER_NORMAL,
                              labelcolor=Colors.TEXT_PRIMARY)

        # Redraw canvas
        self.plot_canvas.draw_idle()

    def _update_channel_button_styles(self):
        """Update toolbar button styles based on visibility state"""
        # Find all QToolButtons in the toolbar that correspond to our channel actions
        for widget in self.plot_toolbar.findChildren(QtWidgets.QToolButton):
            # Check if this button corresponds to one of our channel actions
            action = widget.defaultAction()
            if action in self.ch_actions:
                color = action.property("channel_color")

                if action.isChecked():
                    # Visible: bold font with channel color
                    widget.setStyleSheet(f"""
                        QToolButton {{
                            color: {color};
                            font-weight: bold;
                            background: {Colors.BG_INPUT};
                            border: 1px solid {Colors.BORDER_NORMAL};
                            border-radius: 3px;
                            padding: 3px;
                            margin: 1px;
                        }}
                        QToolButton:hover {{
                            background: {Colors.AKAKUCHIBA};
                            border-color: {Colors.BORDER_FOCUS};
                        }}
                        QToolButton:pressed {{
                            background: {Colors.DEEP_BLUE};
                        }}
                    """)
                else:
                    # Hidden: grey color, normal font
                    widget.setStyleSheet(f"""
                        QToolButton {{
                            color: #808A98;
                            font-weight: normal;
                            background: {Colors.BG_INPUT};
                            border: 1px solid {Colors.BORDER_NORMAL};
                            border-radius: 3px;
                            padding: 3px;
                            margin: 1px;
                        }}
                        QToolButton:hover {{
                            background: {Colors.AKAKUCHIBA};
                            border-color: {Colors.BORDER_FOCUS};
                        }}
                    """)

    # ---------- Toolbar Action Styling Helpers ----------
    def _ensure_action_text_only(self, action: QtWidgets.QAction):
        """Ensure the toolbar shows text for the given action, with bold font."""
        try:
            btn = self.plot_toolbar.widgetForAction(action)
        except Exception:
            btn = None

        if btn is None:
            for w in self.plot_toolbar.findChildren(QtWidgets.QToolButton):
                if w.defaultAction() is action:
                    btn = w
                    break

        if isinstance(btn, QtWidgets.QToolButton):
            btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
            btn.setStyleSheet(f"""
                QToolButton {{
                    font-weight: bold;
                    background: {Colors.BG_INPUT};
                    color: {Colors.TEXT_PRIMARY};
                    border: 1px solid {Colors.BORDER_NORMAL};
                    border-radius: 3px;
                    padding: 3px;
                    margin: 1px;
                }}
                QToolButton:hover {{
                    background: {Colors.AKAKUCHIBA};
                    border-color: {Colors.BORDER_FOCUS};
                }}
                QToolButton:pressed {{
                    background: {Colors.DEEP_BLUE};
                }}
            """)

    def _update_toggle_action_style(self, action: QtWidgets.QAction, active_color: str):
        """Color the action's toolbutton when checked, keep neutral when not."""
        try:
            btn = self.plot_toolbar.widgetForAction(action)
        except Exception:
            btn = None

        if btn is None:
            for w in self.plot_toolbar.findChildren(QtWidgets.QToolButton):
                if w.defaultAction() is action:
                    btn = w
                    break

        if isinstance(btn, QtWidgets.QToolButton):
            if action.isChecked():
                btn.setStyleSheet(f"""
                    QToolButton {{
                        font-weight: bold;
                        color: {active_color};
                        background: {Colors.BG_INPUT};
                        border: 1px solid {Colors.BORDER_FOCUS};
                        border-radius: 3px;
                        padding: 3px;
                        margin: 1px;
                    }}
                    QToolButton:hover {{
                        background: {Colors.AKAKUCHIBA};
                        border-color: {Colors.BORDER_FOCUS};
                    }}
                    QToolButton:pressed {{
                        background: {Colors.DEEP_BLUE};
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QToolButton {{
                        font-weight: bold;
                        color: {Colors.TEXT_PRIMARY};
                        background: {Colors.BG_INPUT};
                        border: 1px solid {Colors.BORDER_NORMAL};
                        border-radius: 3px;
                        padding: 3px;
                        margin: 1px;
                    }}
                    QToolButton:hover {{
                        background: {Colors.AKAKUCHIBA};
                        border-color: {Colors.BORDER_FOCUS};
                    }}
                    QToolButton:pressed {{
                        background: {Colors.DEEP_BLUE};
                    }}
                """)

    # ---------- Channel Enable/Disable ----------
    def _toggle_plot_channel(self, i: int):
        """Toggle enable/disable state for plot channel i"""
        self.plot_active[i] = not self.plot_active[i]
        self._apply_plot_channel_style(i)

    def _apply_plot_channel_style(self, i: int):
        """Apply visual style to channel label and combobox based on enabled state"""
        channel_colors = [Colors.BENIUKON, Colors.MINT_GLOW, Colors.SOFT_YELLOW, Colors.ROSE_CORAL]
        if self.plot_active[i]:
            # Enabled: use channel-specific color
            self.plotLabels[i].setStyleSheet(
                f"color:{channel_colors[i]}; font-weight:700; "
                f"border:2px solid {channel_colors[i]}; border-radius:4px; padding:4px;"
            )
            self.plotCombos[i].setEnabled(True)
            # Set combobox border to match channel color
            self.plotCombos[i].setStyleSheet(f"font-size:12px; font-weight:500; border:2px solid {channel_colors[i]};")
        else:
            # Disabled: greyed out
            self.plotLabels[i].setStyleSheet(
                "color:#808A98; font-weight:700; "
                "border:2px solid #808A98; border-radius:4px; padding:4px;"
            )
            self.plotCombos[i].setEnabled(False)
            # Apply grey border to combobox
            self.plotCombos[i].setStyleSheet(
                f"font-size:12px; font-weight:500; "
                f"border:2px solid #808A98;"
            )

    # ---------- Toolbar Integration Helper ----------
    def _toolbar_push_current(self):
        """
        Push current view to Matplotlib NavigationToolbar's view stack.
        Call this BEFORE changing xlim/ylim/autoscale so Back/Forward/Home can restore states.
        """
        try:
            if hasattr(self, "plot_toolbar") and self.plot_toolbar is not None:
                self.plot_toolbar.push_current()
        except Exception:
            pass

    # ---------- Plot Event Connections ----------
    def _connect_plot_events(self):
        """Connect interactive zoom events to the plot canvas"""
        # Mouse wheel zoom
        self.plot_canvas.mpl_connect('scroll_event', self._on_scroll_zoom)

        # Double-click to reset
        self.plot_canvas.mpl_connect('button_press_event', self._on_mouse_press)

        # Drag rectangle zoom
        self.plot_canvas.mpl_connect('button_press_event', self._on_drag_start)
        self.plot_canvas.mpl_connect('button_release_event', self._on_drag_end)
        self.plot_canvas.mpl_connect('motion_notify_event', self._on_drag_motion)

        # Rectangle selection state
        self.drag_start = None
        self.drag_rect = None

    def _on_scroll_zoom(self, event):
        """Handle mouse wheel zoom centered on cursor position"""
        if event.inaxes != self.plot_ax:
            return

        # Push current view to toolbar history before zooming
        self._toolbar_push_current()

        # Get current axis limits
        cur_xlim = self.plot_ax.get_xlim()
        cur_ylim = self.plot_ax.get_ylim()

        # Save current state to zoom history before zooming
        if not self.manual_zoom_active:
            self.zoom_history = [(cur_xlim, cur_ylim)]

        # Get cursor position
        xdata = event.xdata
        ydata = event.ydata

        # Zoom factor (scroll up = zoom in, scroll down = zoom out)
        if event.button == 'up':
            scale_factor = 0.8
        elif event.button == 'down':
            scale_factor = 1.25
        else:
            return

        # Calculate new limits centered on cursor
        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor

        relx = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
        rely = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])

        new_xlim = [xdata - new_width * (1 - relx), xdata + new_width * relx]
        new_ylim = [ydata - new_height * (1 - rely), ydata + new_height * rely]

        # Apply new limits
        self.plot_ax.set_xlim(new_xlim)
        self.plot_ax.set_ylim(new_ylim)
        self.manual_zoom_active = True
        self.plot_canvas.draw_idle()

    def _on_mouse_press(self, event):
        """Handle mouse button press for double-click reset and right-click zoom out"""
        if event.inaxes != self.plot_ax:
            return

        # FIXED: Double-click uses same method as Home button for consistency
        if event.dblclick:
            self._on_home_clicked()  # Use same method for consistency
            return

        # Right-click: zoom out one level
        if event.button == 3:  # Right mouse button
            self._toolbar_push_current()
            if self.zoom_history:
                xlim, ylim = self.zoom_history.pop()
                self.plot_ax.set_xlim(xlim)
                self.plot_ax.set_ylim(ylim)
                if not self.zoom_history:
                    self.manual_zoom_active = False
                self.plot_canvas.draw_idle()
                self._set_status("Zoomed out one level")
            else:
                # Already at base level, reset to auto
                self.manual_zoom_active = False
                self.plot_ax.relim()
                self.plot_ax.autoscale_view()
                self.plot_canvas.draw_idle()
                self._set_status("Zoom reset to auto-scale")

    def _on_drag_start(self, event):
        """Start drag rectangle zoom"""
        if event.inaxes != self.plot_ax:
            return

        # Only left mouse button for drag zoom
        if event.button == 1 and not event.dblclick:
            self.drag_start = (event.xdata, event.ydata)

    def _on_drag_motion(self, event):
        """Draw selection rectangle during drag"""
        if self.drag_start is None or event.inaxes != self.plot_ax:
            return

        # Remove previous rectangle if exists
        if self.drag_rect is not None:
            self.drag_rect.remove()
            self.drag_rect = None

        # Draw new rectangle
        x0, y0 = self.drag_start
        x1, y1 = event.xdata, event.ydata
        width = x1 - x0
        height = y1 - y0

        self.drag_rect = self.plot_ax.add_patch(
            plt.Rectangle((x0, y0), width, height,
                         fill=False, edgecolor=Colors.SOFT_YELLOW,
                         linewidth=2, linestyle='--', alpha=0.8)
        )
        self.plot_canvas.draw_idle()

    def _on_drag_end(self, event):
        """Complete drag rectangle zoom"""
        if self.drag_start is None or event.inaxes != self.plot_ax:
            self.drag_start = None
            return

        # Only process left mouse button
        if event.button != 1:
            self.drag_start = None
            return

        x0, y0 = self.drag_start
        x1, y1 = event.xdata, event.ydata

        # Remove rectangle
        if self.drag_rect is not None:
            self.drag_rect.remove()
            self.drag_rect = None

        self.drag_start = None

        # Only zoom if drag was significant (> 5 pixels)
        if abs(x1 - x0) < 0.01 or abs(y1 - y0) < 0.01:
            self.plot_canvas.draw_idle()
            return

        # Save current state to history
        if not self.manual_zoom_active:
            cur_xlim = self.plot_ax.get_xlim()
            cur_ylim = self.plot_ax.get_ylim()
            self.zoom_history = [(cur_xlim, cur_ylim)]
        else:
            # Push current view to history stack
            self.zoom_history.append((self.plot_ax.get_xlim(), self.plot_ax.get_ylim()))

        # Push current view to toolbar history before applying new limits
        self._toolbar_push_current()

        # Apply zoom to selected rectangle
        self.plot_ax.set_xlim(sorted([x0, x1]))
        self.plot_ax.set_ylim(sorted([y0, y1]))
        self.manual_zoom_active = True
        self.plot_canvas.draw_idle()
        self._set_status("Zoomed to selection")

    # ---------- Status ----------
    def _set_status(self, msg: str):
        """Update status bar"""
        self.status.showMessage(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def _resolve_setting_path(self, name_or_path: str) -> str:
        """Resolve a stored filename relative to ./setting, or return full path.

        The .dmem stores filenames only. If a full/relative path is provided,
        return it as-is; otherwise, map filename to ./setting/<filename>.
        """
        if not name_or_path:
            return ""
        try:
            p = Path(name_or_path)
            # If it has any parent component (path separators), treat as a path
            if p.name != name_or_path:
                return str(p)
            return str(Path('./setting') / name_or_path)
        except Exception:
            return str(Path('./setting') / name_or_path)

    def _set_mode(self, mode: str, persist: bool = False):
        """Set current mode and reload 0x04 definitions.

        Args:
            mode: Mode name (e.g., "Normal", "Bypass", "Inverter", "Converter", "Gsensor")
            persist: If True, save mode to ./setting/last_mode.txt for next startup
        """
        if not mode or mode == self.mode:
            return

        self.mode = mode

        # Apply 04 definition for current mode from memory
        self._apply_04_for_current_mode()
        self._set_status(f"Mode set to {self.mode}")

        if persist:
            try:
                os.makedirs('./setting', exist_ok=True)
                with open('./setting/last_mode.txt', 'w', encoding='utf-8') as f:
                    f.write(self.mode)
            except Exception:
                pass

    def _restore_last_mode(self):
        """Restore last mode from ./setting/last_mode.txt if it exists."""
        try:
            mode_file = Path('./setting/last_mode.txt')
            if mode_file.exists():
                with open(mode_file, 'r', encoding='utf-8') as f:
                    saved_mode = f.read().strip()
                    if saved_mode:
                        self.mode = saved_mode
        except Exception:
            pass  # Keep default mode on any error

    def _update_window_size_display(self):
        """Update status bar to show current window size"""
        width = self.width()
        height = self.height()
        scale = getattr(self, 'ui_scale', 1.0)
        self.status.showMessage(f"Window: {width}×{height} | Scale: {scale:.2f}")

    def resizeEvent(self, event):
        """Handle window resize events to update size display"""
        super().resizeEvent(event)
        self._update_window_size_display()

    def center_on_screen(self):
        """Center window on primary screen.

        This method calculates the center position of the primary screen's available
        geometry and moves the window to that center position. Works correctly on
        multiple resolutions and multi-monitor setups.

        Compatible with PyInstaller/Nuitka packaging.
        """
        # Get the primary screen's available geometry (excludes taskbar/dock areas)
        screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return  # Fallback: cannot center if no screen detected

        screen_geometry = screen.availableGeometry()

        # Get window's frame geometry (includes title bar and borders)
        window_geometry = self.frameGeometry()

        # Calculate center point of the screen
        center_point = screen_geometry.center()

        # Move window's center to screen's center
        window_geometry.moveCenter(center_point)

        # Move the window to the calculated position
        self.move(window_geometry.topLeft())

    # ---------- Timing Handlers ----------
    def _on_timeout_changed(self):
        """Sync timeout variable from UI and normalize value."""
        try:
            val = int(self.edTimeout.text())
            if val < 1:
                val = 1
            self.timeout_ms = val
            # Normalize UI text
            self.edTimeout.setText(str(val))
        except Exception:
            # Revert to last known good value
            self.edTimeout.setText(str(self.timeout_ms))

    def _on_poll_changed(self):
        """Sync poll interval variable from UI and enforce minimum."""
        try:
            val = int(self.edPoll.text())
            if val < 50:
                val = 50
            self.poll_interval_ms = val
            # Normalize UI text
            self.edPoll.setText(str(val))
        except Exception:
            self.edPoll.setText(str(self.poll_interval_ms))

    def _set_connected_ui(self, connected: bool):
        """Update UI for connection state"""
        if connected:
            self.btnConnect.setText("Disconnect")
            self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.ROSE_CORAL};}} QPushButton:pressed{{background:{Colors.BTN_DANGER_BG};}}")
        else:
            self.btnConnect.setText("Connect")
            self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}")

    # ---------- Ports & Connection ----------
    def _refresh_ports(self):
        """Refresh available COM ports"""
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.cmbPort.clear()
        if ports:
            self.cmbPort.addItems(ports)
            self.cmbPort.setCurrentIndex(0)
            self._set_status("Ports refreshed")
        else:
            self.cmbPort.addItem("No ports available")
            self._set_status("No ports available")

    def _toggle_connection(self):
        """Toggle serial connection"""
        if self.serial_mgr.connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        """Connect to serial port"""
        try:
            port = self.cmbPort.currentText()
            if not port or "No ports" in port:
                raise ValueError("Please select a valid COM port")

            baudrate = int(self.cmbBaud.currentText())
            databits = int(self.cmbDataBits.currentText())
            parity = self.cmbParity.currentText().split('(')[-1].strip(')')
            stopbits = int(self.cmbStopBits.currentText())
            timeout = self.timeout_ms / 1000.0

            ok, msg = self.serial_mgr.connect_port(port, baudrate, databits, parity, stopbits, timeout)
            if ok:
                self._set_connected_ui(True)
                self._set_status(f"{msg} @ {baudrate} baud")
                # Query mode indicator after 200ms
                QtCore.QTimer.singleShot(200, self._query_mode_indicator_once)
            else:
                raise RuntimeError(msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Connection Error", str(e))
            self._set_status(f"Connection failed: {e}")

    def _disconnect(self):
        """Disconnect from serial port"""
        try:
            if self.worker:
                self._stop_polling()
            self.serial_mgr.disconnect_port()
            self._set_connected_ui(False)
            # Turn off mode indicator lights on disconnect
            self._on_mode_indicator_update(None)
            self._set_status("Disconnected")
        except Exception as e:
            self._set_status(f"Disconnect error: {e}")

    # ---------- Address Definitions ----------
    def _init_load_memory(self):
        """Auto-load address definitions from saved memory or default path."""
        try:
            # Sync runtime dict from memory (filenames)
            self.file_04_dict = dict(self.load_mem.file_04)

            # Try load 03 definitions
            if self.load_mem.file_03:
                p03 = Path(self._resolve_setting_path(self.load_mem.file_03))
                if p03.exists():
                    self._load_definitions_file(str(p03))
                    try:
                        self.current_file_03 = p03.name
                    except Exception:
                        pass
                else:
                    self._set_status(f"03 def missing: {p03.name}")

            # Try load current mode's 04 definitions
            mode_file = self.file_04_dict.get(self.mode, "")
            p04 = Path(self._resolve_setting_path(mode_file)) if mode_file else None
            if p04 and p04.exists():
                self._load_input_defs_from_file(str(p04))
                try:
                    self.current_file_04_by_mode[self.mode] = p04.name
                except Exception:
                    pass
            elif mode_file:
                self._set_status(f"04 def missing for {self.mode}: {Path(mode_file).name}")
        except Exception:
            pass

        # If nothing loaded for 04, fall back to default pattern-based lookup
        if not hasattr(self, 'input_defs') or not self.input_defs or all(d.title.startswith('IN') and d.title[2:].isdigit() for d in self.input_defs if hasattr(d, 'title')):
            try:
                folder = Path('./setting')
                # Try mode-specific file first, then generic fallback
                candidates = [
                    folder / f"__address_04def_{self.mode}.ddata",
                    folder / "__address_04def.ddata"
                ]
                def_path = next((p for p in candidates if p.exists()), None)
                if def_path:
                    self._load_input_defs_from_file(str(def_path))
                    try:
                        self.current_file_04_by_mode[self.mode] = def_path.name
                    except Exception:
                        pass
            except Exception:
                pass

        # If nothing loaded for 03, fall back to default
        if not hasattr(self, 'addr_items') or not self.addr_items:
            try:
                default_path = Path('./setting/__address_03def.ddata')
                if default_path.exists():
                    self._load_definitions_file(str(default_path))
                    try:
                        self.current_file_03 = default_path.name
                    except Exception:
                        pass
            except Exception:
                pass

    # Backward compatibility alias
    def _auto_load_definitions(self):
        self._init_load_memory()

    def _apply_04_for_current_mode(self):
        """Apply the 04 definition file for the current mode using memory."""
        try:
            mode_file = self.file_04_dict.get(self.mode, "")
            resolved = self._resolve_setting_path(mode_file) if mode_file else ""
            if resolved and Path(resolved).exists():
                self._load_input_defs_from_file(resolved)
                self._update_input_titles()
                self._set_status(f"Loaded 04 {self.mode}: {Path(resolved).name}")
                try:
                    self.current_file_04_by_mode[self.mode] = Path(resolved).name
                except Exception:
                    pass
            elif mode_file:
                self._set_status(f"04 def missing for {self.mode}: {Path(mode_file).name}")
        except Exception as e:
            self._set_status(f"Failed to load 04 for {self.mode}: {e}")

    def _load_input_defs(self, mode: str = None):
        """Load 0x04 input register definitions for given mode.

        Args:
            mode: Mode name (e.g., "Normal", "Bypass", "Inverter").
                  Will try __address_04def_{mode}.ddata first,
                  then fallback to __address_04def.ddata.
        """
        # Initialize with defaults for all 12 input registers
        self.input_defs = [InputRegDef.create_default(i) for i in range(12)]

        try:
            folder = Path('./setting')
            candidates = []

            # If mode is specified, try mode-specific file first
            if mode:
                candidates.append(folder / f"__address_04def_{mode}.ddata")

            # Fallback to generic definition file
            candidates.append(folder / "__address_04def.ddata")

            # Find first existing file
            def_path = next((p for p in candidates if p.exists()), None)
            if not def_path:
                return  # Use defaults

            with open(def_path, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]

            # Only use first 8 lines (IN0..IN7)
            for idx, line in enumerate(lines[:8]):
                if idx >= 8:
                    break

                # Parse CSV-like format: [Title],[Format],[Ratio],[Show]
                parts = [p.strip() for p in line.split(',')]

                # Extract fields with defaults
                title = parts[0] if len(parts) > 0 and parts[0] else f"IN{idx}"
                fmt = parts[1].lower() if len(parts) > 1 and parts[1] else "value"

                # Validate format
                if fmt not in ("value", "bitstatus", "valstatus"):
                    fmt = "value"

                # Parse ratio
                ratio = 1.0
                if len(parts) > 2 and parts[2]:
                    try:
                        ratio = float(parts[2])
                    except ValueError:
                        ratio = 1.0

                # Parse show field
                show_raw = parts[3] if len(parts) > 3 and parts[3] else ""

                if fmt == "value":
                    # For value format: default "int16", or "uint16"
                    show = show_raw if show_raw in ("int16", "uint16") else "int16"
                elif fmt == "bitstatus":
                    # For bitstatus: default "1/0" or custom labels
                    if not show_raw or show_raw == "1/0":
                        show = "1/0"
                    else:
                        # Split custom labels by "|" - MSB to LSB
                        labels = show_raw.split('|')
                        # Truncate to max 16 labels (do NOT auto-pad)
                        labels = labels[:16]
                        show = labels
                elif fmt == "valstatus":
                    # Use raw value as 0-based index into labels; out-of-range => "NA"
                    # Limit to at most 16 labels
                    labels = [s.strip() for s in show_raw.split('|')] if show_raw else []
                    labels = labels[:16]
                    show = labels

                # Store the definition
                self.input_defs[idx] = InputRegDef(
                    title=title,
                    fmt=fmt,
                    ratio=ratio,
                    show=show
                )

        except Exception:
            # On any error, keep defaults
            pass

        # Automatically update UI titles after loading
        try:
            self._update_input_titles()
        except Exception:
            pass

    def _update_input_titles(self):
        """Update input register title labels from loaded definitions"""
        if not hasattr(self, 'input_defs') or not hasattr(self, 'inputRegLabels'):
            return

        for i in range(min(12, len(self.input_defs), len(self.inputRegLabels))):
            self.inputRegLabels[i].setText(self.input_defs[i].title)

    def _load_definitions_dialog(self):
        """Show custom dialog to select 03 and 04 definition files"""
        dialog = LoadSettingsDialog(self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            # Get selected filenames (not full paths)
            file_03 = dialog.get_selected_03_file()
            file_04_dict = dialog.get_selected_04_files()

            # Update unified memory and persist
            self.load_mem.file_03 = file_03
            self.load_mem.file_04 = dict(file_04_dict)
            self.load_mem.save()

            # Apply the selections
            self._apply_load_settings(file_03, file_04_dict)

            # No message box after apply per request; rely on status bar updates

    # Public alias requested
    def open_load_dialog(self):
        self._load_definitions_dialog()

    def open_device_info_dialog(self):
        """Open the Device Information dialog (non-modal)"""
        try:
            dialog = DeviceInformationDialog(self)
            dialog.show()
        except Exception as e:
            self._set_status(f"Error opening Device Information: {str(e)}")

    def _apply_load_settings(self, file_03: str, file_04_dict: dict):
        """Apply selected definition files (filenames, resolved under ./setting)."""
        try:
            # Load 03 file (holding registers), resolve to ./setting
            if file_03:
                p03 = self._resolve_setting_path(file_03)
                if p03 and Path(p03).exists():
                    self._load_definitions_file(p03)
                    self._set_status(f"Loaded 03 definitions: {Path(p03).name}")
                    try:
                        self.current_file_03 = Path(p03).name
                    except Exception:
                        pass

            # Store 04 filenames in a dictionary for later mode-based loading
            self.file_04_dict = dict(file_04_dict)

            # Load the current mode's 04 file
            current_mode_file = file_04_dict.get(self.mode, "")
            if current_mode_file:
                p04 = self._resolve_setting_path(current_mode_file)
                if p04 and Path(p04).exists():
                    self._load_input_defs_from_file(p04)
                    self._set_status(f"Loaded 04 {self.mode} definitions: {Path(p04).name}")
                    try:
                        self.current_file_04_by_mode[self.mode] = Path(p04).name
                    except Exception:
                        pass

            loaded_count = sum(1 for v in file_04_dict.values() if v)
            if file_03 or loaded_count > 0:
                self._set_status(f"Loaded definitions successfully (03 + {loaded_count} 04 types)")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load Error", f"Failed to apply settings:\n{e}")
            self._set_status(f"Failed to apply load settings: {e}")

    

    def _load_input_defs_from_file(self, filepath: str):
        """Load 0x04 input register definitions from a specific file"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]

            # Initialize with defaults
            self.input_defs = [InputRegDef.create_default(i) for i in range(12)]

            # Use first 12 lines (IN0..IN11)
            for idx, line in enumerate(lines[:12]):
                if idx >= 12:
                    break

                # Parse CSV-like format: [Title],[Format],[Ratio],[Show]
                parts = [p.strip() for p in line.split(',')]

                # Extract fields with defaults
                title = parts[0] if len(parts) > 0 and parts[0] else f"IN{idx}"
                fmt = parts[1].lower() if len(parts) > 1 and parts[1] else "value"

                # Validate format
                if fmt not in ("value", "bitstatus", "valstatus"):
                    fmt = "value"

                # Parse ratio
                ratio = 1.0
                if len(parts) > 2 and parts[2]:
                    try:
                        ratio = float(parts[2])
                    except ValueError:
                        ratio = 1.0

                # Parse show field
                show_raw = parts[3] if len(parts) > 3 and parts[3] else ""

                if fmt == "value":
                    show = show_raw if show_raw in ("int16", "uint16") else "int16"
                elif fmt == "bitstatus":
                    if not show_raw or show_raw == "1/0":
                        show = "1/0"
                    else:
                        labels = show_raw.split('|')
                        labels = labels[:16]
                        show = labels
                elif fmt == "valstatus":
                    labels = [s.strip() for s in show_raw.split('|')] if show_raw else []
                    labels = labels[:16]
                    show = labels

                # Store the definition
                self.input_defs[idx] = InputRegDef(
                    title=title,
                    fmt=fmt,
                    ratio=ratio,
                    show=show
                )

            # Update UI
            self._update_input_titles()
            try:
                # Track last loaded 04 per current mode for dialog display
                self.current_file_04_by_mode[self.mode] = Path(filepath).name
            except Exception:
                pass
        except Exception as e:
            raise Exception(f"Failed to load 04 definitions: {e}")

    def _load_definitions_file(self, filepath: str):
        """Load address definitions from file

        Supports two formats:
        1. Simple format (line number becomes address):
           Register_Name_1
           Register_Name_2

        2. Address_Name format (custom address numbers):
           0_Register_Name_1
           5_Register_Name_2
           100_Register_Name_3
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            if not lines:
                raise ValueError("File is empty")

            self.addr_items = []
            for i, line in enumerate(lines):
                # Check if line already has address_name format (starts with digits_)
                if '_' in line:
                    parts = line.split('_', 1)
                    if parts[0].isdigit():
                        # Already has address number, use as-is
                        addr_num = int(parts[0])
                        self.addr_items.append(f"{addr_num:03d}_{parts[1]}")
                    else:
                        # Has underscore but not address format, use line number
                        self.addr_items.append(f"{i:03d}_{line}")
                else:
                    # No underscore, use line number as address
                    self.addr_items.append(f"{i:03d}_{line}")

            # Update all combo boxes (monitor rows and plot channels)
            for combo in self.rowCombos:
                combo.clear()
                combo.addItems(self.addr_items)
                if self.addr_items:
                    combo.setCurrentIndex(0)

            # Update plot combo boxes
            for combo in self.plotCombos:
                combo.clear()
                combo.addItem("---")
                combo.addItems(self.addr_items)
                combo.setCurrentIndex(0)

            fname = Path(filepath).name
            self._set_status(f"Loaded {len(lines)} addresses from {fname}")
            try:
                # Track last loaded 03 file for dialog display
                self.current_file_03 = Path(filepath).name
            except Exception:
                pass
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load file:\n{e}")
            self._set_status(f"Failed to load file: {e}")

    # ---------- Polling ----------
    def _toggle_polling(self):
        """Toggle auto-polling"""
        if self.worker and self.worker.isRunning():
            self._stop_polling()
        else:
            # Ensure plotting is stopped before starting polling
            if self.plot_worker and self.plot_worker.isRunning():
                self._stop_plotting()
            self._start_polling()

    # ---------- Motor Control ----------
    def _send_motor_value(self):
        """Send motor value (0-65535) to register 0x0102 using FC 0x06."""
        if not self.serial_mgr.connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Please connect to a serial port first")
            return
        try:
            slave_id = int(self.edSlave.text())
            timeout = self.timeout_ms / 1000.0

            txt = self.edMotorValue.text().strip()
            if not txt:
                raise ValueError("Please enter a motor value (0-65535)")
            value = int(txt)
            if not (0 <= value <= 65535):
                raise ValueError("Motor value must be between 0 and 65535")

            addr = 0x0102
            req = ModbusRTU.write_single_register(slave_id, addr, value)
            ok, result = self.serial_mgr.transact(req, slave_id, 0x06, timeout=timeout, post_quiet_ms=100)
            if not ok:
                raise RuntimeError(result)

            # Keep the motor value in the input box (don't clear it)
            self._set_status(f"Motor command sent: addr 0x{addr:04X} = {value}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Motor Control Error", str(e))
            self._set_status(f"Motor control failed: {e}")

    def _stop_motor(self):
        """Send 0x0000 to register 0x0102 (Stop)."""
        if not self.serial_mgr.connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Please connect to a serial port first")
            return
        try:
            slave_id = int(self.edSlave.text())
            timeout = self.timeout_ms / 1000.0
            addr = 0x0102
            value = 0x0000
            req = ModbusRTU.write_single_register(slave_id, addr, value)
            ok, result = self.serial_mgr.transact(req, slave_id, 0x06, timeout=timeout, post_quiet_ms=100)
            if not ok:
                raise RuntimeError(result)

            # Do not clear input per spec
            self._set_status(f"Motor STOP sent: addr 0x{addr:04X} = {value}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Motor Control Error", str(e))
            self._set_status(f"Motor control failed: {e}")

    def _send_rd_command(self, cmd_hex: str, btn_text: str):
        """Send RD special command (raw hex with auto CRC)"""
        if not self.serial_mgr.connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Please connect to a serial port first")
            return
        try:
            # Stop polling and plotting before mode switch
            if self.worker and self.worker.isRunning():
                self._stop_polling()
                self._set_status("Polling stopped for mode switch")

            if self.plot_worker and self.plot_worker.isRunning():
                self._stop_plotting()
                self._set_status("Plotting stopped for mode switch")

            # Convert hex string to bytes
            cmd_bytes = bytes.fromhex(cmd_hex)
            # Calculate and append CRC16
            crc = ModbusRTU.crc16(cmd_bytes)
            frame = cmd_bytes + struct.pack("<H", crc)

            # Send directly via serial port (no response check)
            self.serial_mgr.port.write(frame)
            self.serial_mgr.port.flush()

            # Switch to the corresponding mode
            self._set_mode(btn_text)

            self._set_status(f"{btn_text} command sent")
            # Query mode indicator after 1 second
            QtCore.QTimer.singleShot(2000, self._query_mode_indicator_once)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "RD Command Error", str(e))
            self._set_status(f"RD command failed: {e}")

    def _send_reset_command(self, cmd_hex: str, btn_text: str):
        """Send Reset special command (raw hex with auto CRC)"""
        if not self.serial_mgr.connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Please connect to a serial port first")
            return
        try:
            # Convert hex string to bytes
            cmd_bytes = bytes.fromhex(cmd_hex)
            # Calculate and append CRC16
            crc = ModbusRTU.crc16(cmd_bytes)
            frame = cmd_bytes + struct.pack("<H", crc)

            # Send directly via serial port (no response check)
            self.serial_mgr.port.write(frame)
            self.serial_mgr.port.flush()

            self._set_status(f"{btn_text} command sent")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Reset Command Error", str(e))
            self._set_status(f"Reset command failed: {e}")

    def _send_switch_command(self):
        """Send Switch command based on current combobox selection, then update ID field."""
        if not self.serial_mgr.connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Please connect to a serial port first")
            return
        try:
            # Stop polling and plotting before mode switch
            if self.worker and self.worker.isRunning():
                self._stop_polling()
                self._set_status("Polling stopped for mode switch")

            if self.plot_worker and self.plot_worker.isRunning():
                self._stop_plotting()
                self._set_status("Plotting stopped for mode switch")

            # selection -> (cmd_hex, new_slave_id)
            mapping = {
                "Inverter":  ("014600070001024708", 1),
                "Converter": ("014600070001023908", 2),
                "Gsensor":   ("014600070001025A08", 3),
            }

            selected = self.rdCombo.currentText()
            pair = mapping.get(selected)
            if not pair:
                raise ValueError(f"Unknown selection: {selected}")

            cmd_hex, new_id = pair

            # Convert hex string to bytes + append CRC16
            cmd_bytes = bytes.fromhex(cmd_hex)
            crc = ModbusRTU.crc16(cmd_bytes)
            frame = cmd_bytes + struct.pack("<H", crc)

            # Send directly via serial port (no response check)
            self.serial_mgr.port.write(frame)
            self.serial_mgr.port.flush()

            # Update the ID field to the corresponding number
            self.edSlave.setText(str(new_id))

            # Switch to the corresponding mode
            self._set_mode(selected)

            self._set_status(f"Switch command sent: {selected} → ID set to {new_id}")
            # Query mode indicator after 1 second
            QtCore.QTimer.singleShot(1000, self._query_mode_indicator_once)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Switch Command Error", str(e))
            self._set_status(f"Switch command failed: {e}")

    def _start_polling(self):
        """Start auto-polling"""
        if not self.serial_mgr.connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Please connect to a serial port first")
            return
        try:
            interval_ms = self.poll_interval_ms
            if interval_ms < 50:
                raise ValueError("Poll interval must be >= 50ms")

            def get_row_addr(idx: int) -> Optional[int]:
                txt = self.rowCombos[idx].currentText()
                if not txt or txt == "---":
                    return None
                try:
                    return int(txt.split('_', 1)[0])
                except:
                    return None

            def get_cfg():
                slave = int(self.edSlave.text())
                timeout = self.timeout_ms / 1000.0
                interval = self.poll_interval_ms / 1000.0
                return slave, timeout, interval

            self.worker = PollWorker(self.serial_mgr, get_row_addr, get_cfg, self)
            self.worker.sigRegister.connect(self._on_register_update)
            self.worker.sigInputRegisters.connect(self._on_input_registers_update)
            self.worker.sigModeIndicator.connect(self._on_mode_indicator_update)
            self.worker.sigStatus.connect(self._set_status)
            self.worker.start()

            self.btnPolling.setText("End")
            self.btnPolling.setStyleSheet(f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.ROSE_CORAL};}} QPushButton:pressed{{background:{Colors.BTN_DANGER_BG};}}")
            self._set_status("Polling started")
            # Query mode indicator after 200ms
            QtCore.QTimer.singleShot(200, self._query_mode_indicator_once)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            self._set_status(f"Failed to start polling: {e}")

    def _stop_polling(self):
        """Stop auto-polling"""
        if self.worker:
            self.worker.stop()
            self.worker.wait(1500)
            self.worker = None
        # Reset input register displays (all 12 registers)
        for i in range(12):
            self.inputRegValues[i].setText("----")
            self.inputRegValues[i].setStyleSheet(
                f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; "
                f"padding:6px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; "
                f"font-weight:600; font-size:14px;"
            )
        self.btnPolling.setText("Start")
        self.btnPolling.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}")
        self._set_status("Polling stopped")

    @QtCore.pyqtSlot(int, object, object)
    def _on_register_update(self, index: int, value: Optional[int], error: Optional[str]):
        """Update register display from polling thread"""
        if value is not None:
            # Update value and restore normal border
            self.rowValues[index].setText(str(value))
            self.rowValues[index].setStyleSheet(f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; padding:8px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; font-weight:600; font-size:16px;")
        else:
            # Keep existing value but show red border to indicate error
            self.rowValues[index].setStyleSheet(f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; padding:8px; border:2px solid {Colors.STATUS_ERROR}; border-radius:4px; font-weight:600; font-size:16px;")

    def _render_input04(self, index: int, raw_value: int) -> str:
        """Render 0x04 input register value according to its definition"""
        if index < 0 or index >= 8 or not hasattr(self, 'input_defs'):
            return str(raw_value)

        input_def = self.input_defs[index]

        if input_def.fmt == "value":
            # Value format: apply ratio and int16/uint16 conversion
            if input_def.show == "int16":
                # Convert to signed int16
                signed_val = raw_value if raw_value < 32768 else raw_value - 65536
                result = signed_val * input_def.ratio
            else:  # uint16 or default
                # Use unsigned value
                result = raw_value * input_def.ratio

            # Format the number: suppress trailing ".0" if integer
            if result == int(result):
                return str(int(result))
            else:
                return f"{result:.2f}".rstrip('0').rstrip('.')

        elif input_def.fmt == "bitstatus":
            # NEW: If all bits are zero, show "Normal"
            if raw_value == 0:
                return "Normal"

            # Bitstatus format: show bits as 1/0 or custom labels
            if input_def.show == "1/0":
                # Show 16-bit binary representation
                return f"{raw_value:016b}"
            elif isinstance(input_def.show, list):
                # Custom labels: MSB to LSB
                labels = input_def.show
                active_labels = []

                # Iterate through bits from MSB (bit 15) to LSB (bit 0)
                for bit_idx in range(16):
                    bit_position = 15 - bit_idx  # MSB first
                    bit_value = (raw_value >> bit_position) & 1

                    if bit_value == 1:
                        # Check if we have a label for this position
                        if bit_idx < len(labels) and labels[bit_idx]:
                            active_labels.append(labels[bit_idx])
                        # If no label or empty label, skip (undefined bit)

                # Return comma-separated labels, or "Normal" if none active
                return ", ".join(active_labels) if active_labels else "Normal"
            else:
                # Fallback to 1/0 if show format is invalid
                return f"{raw_value:016b}"

        elif input_def.fmt == "valstatus":
            # Map raw_value -> label by 0-based index; out of range => "NA"
            labels = input_def.show if isinstance(input_def.show, list) else []
            try:
                idx = int(raw_value)
            except Exception:
                idx = -1
            if 0 <= idx < len(labels) and labels[idx]:
                return labels[idx]
            return "NA"

        # Fallback: just show raw value
        return str(raw_value)

    @QtCore.pyqtSlot(object, object)  # FIXED: Changed from (list, object) to (object, object) to allow None values
    def _on_input_registers_update(self, values: Optional[List[int]], error: Optional[str]):
        """Update input register displays from polling thread"""
        # FIXED: Add widget existence check to prevent crash on deleted widgets
        if not hasattr(self, 'inputRegValues') or len(self.inputRegValues) != 12:
            return

        try:  # FIXED: Wrap in try-except to catch widget deletion race
            # FIXED: Added isinstance(values, list) check to prevent TypeError
            if values is not None and isinstance(values, list) and len(values) == 12:
                for i, val in enumerate(values):
                    if val is not None:
                        # Use custom rendering based on definition file and restore normal border
                        rendered_text = self._render_input04(i, val)
                        self.inputRegValues[i].setText(rendered_text)
                        self.inputRegValues[i].setStyleSheet(
                            f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; "
                            f"padding:6px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; "
                            f"font-weight:600; font-size:14px;"
                        )
                    else:
                        # Individual register failed - keep existing value but show red border
                        self.inputRegValues[i].setStyleSheet(
                            f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; "
                            f"padding:6px; border:2px solid {Colors.STATUS_ERROR}; border-radius:4px; "
                            f"font-weight:600; font-size:14px;"
                        )
            else:
                # Error case - keep existing values but show red border to indicate error
                for i in range(12):
                    self.inputRegValues[i].setStyleSheet(
                        f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; "
                        f"padding:6px; border:2px solid {Colors.STATUS_ERROR}; border-radius:4px; "
                        f"font-weight:600; font-size:14px;"
                    )
        except (RuntimeError, AttributeError):
            # FIXED: Widget was deleted during update, exit gracefully
            return

    def _query_mode_indicator_once(self):
        """Query mode indicator register 0x0007 once and update UI"""
        if not self.serial_mgr.connected:
            return
        try:
            slave_id = int(self.edSlave.text())
            timeout = self.timeout_ms / 1000.0
            req = ModbusRTU.read_holding_registers(slave_id, 0x0007, 1)
            ok, result = self.serial_mgr.transact(req, slave_id, 0x03, timeout=timeout)
            if ok and isinstance(result, list) and result:
                self._on_mode_indicator_update(int(result[0]))
            else:
                self._on_mode_indicator_update(None)
        except Exception:
            self._on_mode_indicator_update(None)

    @QtCore.pyqtSlot(object)
    def _on_mode_indicator_update(self, value: Optional[int]):
        """Update Normal/Bypass indicator text color based on register 0x0007 value"""
        if value is not None:
            if value == 0:
                # Normal mode (0) - Normal text turns red (ON), Bypass text stays gray (OFF)
                self.lblNormalLight.setStyleSheet(
                    f"QLabel{{color:{Colors.SOFT_YELLOW}; "
                    f"font-weight:700; font-size:{self.tokens.font_large()}px; padding:0px; border:none;}}"
                )
                self.lblBypassLight.setStyleSheet(
                    f"QLabel{{color:{Colors.BG_INPUT}; "
                    f"font-weight:700; font-size:{self.tokens.font_large()}px; padding:0px; border:none;}}"
                )
            else:
                # Bypass mode (non-0) - Normal text stays gray (OFF), Bypass text turns red (ON)
                self.lblNormalLight.setStyleSheet(
                    f"QLabel{{color:{Colors.BG_INPUT}; "
                    f"font-weight:700; font-size:{self.tokens.font_large()}px; padding:0px; border:none;}}"
                )
                self.lblBypassLight.setStyleSheet(
                    f"QLabel{{color:{Colors.SOFT_YELLOW}; "
                    f"font-weight:700; font-size:{self.tokens.font_large()}px; padding:0px; border:none;}}"
                )
        else:
            # Error or disconnected - both texts turn gray (OFF)
            self.lblNormalLight.setStyleSheet(
                f"QLabel{{color:{Colors.BG_INPUT}; "
                f"font-weight:700; font-size:{self.tokens.font_large()}px; padding:0px; border:none;}}"
            )
            self.lblBypassLight.setStyleSheet(
                f"QLabel{{color:{Colors.BG_INPUT}; "
                f"font-weight:700; font-size:{self.tokens.font_large()}px; padding:0px; border:none;}}"
            )

    # ---------- Write ----------
    def _write_register(self, index: int):
        """Write value to register"""
        if not self.serial_mgr.connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Please connect to a serial port first")
            return
        try:
            slave_id = int(self.edSlave.text())
            timeout = self.timeout_ms / 1000.0

            txt = self.rowCombos[index].currentText()
            if not txt:
                raise ValueError("Please select an address")
            addr = int(txt.split('_', 1)[0])

            vtxt = self.rowEdits[index].text().strip()
            if not vtxt:
                raise ValueError("Please enter a value")
            value = int(vtxt)
            if not (0 <= value <= 65535):
                raise ValueError("Value must be between 0 and 65535")

            req = ModbusRTU.write_single_register(slave_id, addr, value)
            ok, result = self.serial_mgr.transact(req, slave_id, 0x06, timeout=timeout, post_quiet_ms=100)
            if not ok:
                raise RuntimeError(result)

            # readback
            rd = ModbusRTU.read_holding_registers(slave_id, addr, 1)
            ok2, res2 = self.serial_mgr.transact(rd, slave_id, 0x03, timeout=timeout)
            shown = value
            if ok2 and isinstance(res2, list) and res2:
                shown = int(res2[0])

            # Keep the value in the edit box (don't clear it)
            self.rowValues[index].setText(str(shown))
            self.rowValues[index].setStyleSheet(f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; padding:8px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; font-weight:600; font-size:16px;")
            self._set_status(f"Write successful: Address {addr} = {shown}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Write Error", str(e))
            self._set_status(f"Write failed: {e}")

    # ---------- Plotting ----------
    def _toggle_plotting(self):
        """Toggle real-time plotting (mode-aware)"""
        if self.current_mode == "03":
            # 03 Mode plotting
            if self.plot_worker and self.plot_worker.isRunning():
                self._stop_plotting()
            else:
                self._start_plotting()
        else:
            # RR Mode plotting
            if self.rr_worker and self.rr_worker.isRunning():
                self._stop_rr_mode()
            else:
                self._start_rr_mode()

    def _start_plotting(self):
        """Start real-time plotting"""
        if not self.serial_mgr.connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Please connect to a serial port first")
            return

        try:
            # Ensure polling is stopped before starting plotting
            if self.worker and self.worker.isRunning():
                self._stop_polling()
            # Clear previous data and reset zoom state
            for ch_data in self.plot_data:
                ch_data['time'].clear()
                ch_data['value'].clear()
            self.plot_start_time = time.time()
            self.manual_zoom_active = False
            self.zoom_history.clear()

            def get_addresses():
                """Get list of 4 addresses from plot combos"""
                addresses = []
                for combo in self.plotCombos:
                    txt = combo.currentText()
                    if not txt or txt == "---":
                        addresses.append(None)
                    else:
                        try:
                            addr = int(txt.split('_', 1)[0])
                            addresses.append(addr)
                        except:
                            addresses.append(None)
                return addresses

            def get_active():
                """Get list of enabled channel indices"""
                return [idx for idx, ok in enumerate(self.plot_active) if ok]

            def get_cfg():
                slave = int(self.edSlave.text())
                timeout = self.timeout_ms / 1000.0
                return slave, timeout

            self.plot_worker = PlotWorker(self.serial_mgr, get_addresses, get_active, get_cfg, self)
            self.plot_worker.sigData.connect(self._on_plot_data)
            self.plot_worker.sigModeIndicator.connect(self._on_mode_indicator_update)
            self.plot_worker.sigStatus.connect(self._set_status)
            self.plot_worker.start()

            self.btnDraw.setText("Stop")
            self.btnDraw.setStyleSheet(f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.ROSE_CORAL};}} QPushButton:pressed{{background:{Colors.BTN_DANGER_BG};}}")
            self._set_status("Plotting started")
            # Query mode indicator after 200ms
            QtCore.QTimer.singleShot(200, self._query_mode_indicator_once)

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            self._set_status(f"Failed to start plotting: {e}")

    def _stop_plotting(self):
        """Stop real-time plotting"""
        if self.plot_worker:
            self.plot_worker.stop()
            self.plot_worker.wait(1500)
            self.plot_worker = None
        self.btnDraw.setText("Draw")
        self.btnDraw.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}")
        self._set_status("Plotting stopped")

    @QtCore.pyqtSlot(int, object, object)
    def _on_plot_data(self, channel: int, value: Optional[int], timestamp: Optional[float]):
        """Update plot with new data point"""
        if value is not None and timestamp is not None:
            # Convert Modbus Uint16 (0-65535) to signed Int16 (-32768 to +32767)
            if value > 32767:
                value -= 65536

            # Store data
            elapsed = timestamp - self.plot_start_time
            self.plot_data[channel]['time'].append(elapsed)
            self.plot_data[channel]['value'].append(value)

            # Keep only last 375 points per channel
            if len(self.plot_data[channel]['time']) > 375:
                self.plot_data[channel]['time'].pop(0)
                self.plot_data[channel]['value'].pop(0)

            # Update plot
            self._update_plot()

    # ---------- RR Mode Methods ----------
    def _toggle_mode(self):
        """Toggle between 03 Mode and RR Mode"""
        if self.current_mode == "03":
            self._switch_to_rr_mode()
        else:
            self._switch_to_03_mode()

    def _switch_to_rr_mode(self):
        """Switch from 03 Mode to RR Mode"""
        # Stop any active polling or plotting
        if self.worker and self.worker.isRunning():
            self._stop_polling()
        if self.plot_worker and self.plot_worker.isRunning():
            self._stop_plotting()

        self.current_mode = "RR"
        self.btnModeSwitch.setText("RR")

        # Enable RR controls, disable 03 mode channel selectors
        self.cmbRRPage.setEnabled(True)
        self.btnLoadDtbpt.setEnabled(True)
        for combo in self.plotCombos:
            combo.setEnabled(False)

        # Update plot button text
        self.btnDraw.setText("Plot (RR)")

        # Clear plot data
        for ch_data in self.rr_data:
            ch_data['x'].clear()
            ch_data['y'].clear()

        # Update titles from .dtbpt file
        self._update_rr_titles()

        self._set_status("Switched to RR Mode")

    def _switch_to_03_mode(self):
        """Switch from RR Mode to 03 Mode"""
        # Stop RR worker if running
        if self.rr_worker and self.rr_worker.isRunning():
            self._stop_rr_mode()

        self.current_mode = "03"
        self.btnModeSwitch.setText("03")

        # Disable RR controls, enable 03 mode channel selectors
        self.cmbRRPage.setEnabled(False)
        self.btnLoadDtbpt.setEnabled(False)
        for combo in self.plotCombos:
            combo.setEnabled(True)

        # Restore 03 Mode combo boxes with address items
        for combo in self.plotCombos:
            combo.clear()
            combo.addItem("---")
            for item in self.addr_items:
                combo.addItem(item)

        # Restore plot legend to Ch1-Ch4
        for i, line in enumerate(self.plot_lines):
            line.set_label(f'Ch{i+1}')
        self.plot_ax.legend(loc='upper left', facecolor=Colors.BG_PANEL,
                           edgecolor=Colors.BORDER_NORMAL, labelcolor=Colors.TEXT_PRIMARY)
        self.plot_canvas.draw_idle()

        # Update plot button text
        self.btnDraw.setText("Draw")

        # Clear plot data
        for ch_data in self.plot_data:
            ch_data['time'].clear()
            ch_data['value'].clear()

        self._set_status("Switched to 03 Mode")

    def _load_default_rr_titles(self):
        """Load default RR title file (RR_title_default.dtbpt) on startup"""
        default_path = Path("./setting/RR_title_default.dtbpt")
        if default_path.exists():
            try:
                self.rr_dtbpt_parser = DtbptParser.load(str(default_path))
            except Exception:
                # If default file fails to load, parser will remain None
                # and _update_rr_titles() will use fallback "Data1-4"
                pass

    def _load_dtbpt_file(self):
        """Open file dialog to load .dtbpt title file"""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load .dtbpt Title File",
            "./setting",
            "Title Files (*.dtbpt);;All Files (*)"
        )

        if file_path:
            try:
                self.rr_dtbpt_parser = DtbptParser.load(file_path)
                self._update_rr_titles()
                self._set_status(f"Loaded {Path(file_path).name}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Load Error", f"Failed to load .dtbpt file:\n{e}")
                self._set_status(f"Failed to load .dtbpt: {e}")

    def _on_rr_page_changed(self, index: int):
        """Handle RR page selection change"""
        self.rr_current_page = index
        self._update_rr_titles()

    def _update_rr_titles(self):
        """Update plot legend and combo boxes with titles from .dtbpt for current page"""
        if self.rr_dtbpt_parser:
            titles = self.rr_dtbpt_parser.get_titles(self.rr_current_page)
        else:
            titles = [f"Data{i+1}" for i in range(4)]

        # Update plot legend
        for i, line in enumerate(self.plot_lines):
            if i < len(titles):
                line.set_label(titles[i])

        self.plot_ax.legend(loc='upper left', facecolor=Colors.BG_PANEL,
                           edgecolor=Colors.BORDER_NORMAL, labelcolor=Colors.TEXT_PRIMARY)
        self.plot_canvas.draw_idle()

        # Update CH1-CH4 combo boxes with current page titles (in RR Mode)
        if self.current_mode == "RR":
            for i, combo in enumerate(self.plotCombos):
                if i < len(titles):
                    # Clear and update with new title
                    combo.clear()
                    combo.addItem(titles[i])
                    combo.setCurrentIndex(0)

    def _start_rr_mode(self):
        """Start RR Mode data acquisition"""
        if not self.serial_mgr.connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Please connect to a serial port first")
            return

        try:
            # Clear previous data
            for ch_data in self.rr_data:
                ch_data['x'].clear()
                ch_data['y'].clear()
            self.manual_zoom_active = False
            self.zoom_history.clear()

            timeout = self.timeout_ms / 1000.0
            self.rr_worker = RRModeWorker(self.serial_mgr, self.rr_current_page, timeout, self)
            self.rr_worker.sigFrame.connect(self._on_rr_frame)
            self.rr_worker.sigStatus.connect(self._set_status)
            self.rr_worker.sigFinished.connect(self._on_rr_finished)
            self.rr_worker.start()

            # Start the plot update timer for throttled redraws
            self.rr_plot_timer.start()

            self.btnDraw.setText("Stop")
            self.btnDraw.setStyleSheet(f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.ROSE_CORAL};}} QPushButton:pressed{{background:{Colors.BTN_DANGER_BG};}}")
            self._set_status(f"RR Mode plotting started (Page {self.rr_current_page})")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            self._set_status(f"Failed to start RR Mode: {e}")

    def _stop_rr_mode(self):
        """Stop RR Mode data acquisition"""
        # Stop the plot update timer
        self.rr_plot_timer.stop()

        if self.rr_worker:
            self.rr_worker.stop()
            self.rr_worker.wait(1500)
            self.rr_worker = None
        self.btnDraw.setText("Plot (RR)")
        self.btnDraw.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}")
        self._set_status("RR Mode stopped")

    @QtCore.pyqtSlot(int, tuple)
    def _on_rr_frame(self, data_group_index: int, values: tuple):
        """Handle RR Mode data frame (one frame contains all 4 channel values)"""
        # values = (d1, d2, d3, d4)
        for ch, value in enumerate(values):
            # Convert to signed int16 if needed
            if value > 32767:
                value -= 65536

            # Store data (deque automatically maintains maxlen)
            self.rr_data[ch]['x'].append(data_group_index)
            self.rr_data[ch]['y'].append(value)

        # Mark data as dirty for timer-based update
        self._rr_dirty = True

    def _update_rr_plot(self):
        """Update plot with RR Mode data (X = Data Group Index, Y = values)

        Optimized for high-frequency updates:
        - Only updates if data has changed (_rr_dirty flag)
        - Uses sliding X-axis window instead of full autoscale
        - Throttles Y-axis autoscale to every 10th frame
        - Uses draw_idle() for non-blocking redraw
        """
        if not self._rr_dirty:
            return
        self._rr_dirty = False

        try:
            # Update line data and find maximum X value
            xmax = None
            for i, line in enumerate(self.plot_lines):
                x_data = self.rr_data[i]['x']
                y_data = self.rr_data[i]['y']
                if x_data:
                    curr_xmax = x_data[-1]
                    xmax = curr_xmax if xmax is None else max(xmax, curr_xmax)
                line.set_data(x_data, y_data)

            # Only auto-scale if manual zoom is not active
            if not self.manual_zoom_active:
                # Sliding X-axis window: show the last W points
                if xmax is not None:
                    self.plot_ax.set_xlim(xmax - self.rr_window_width, xmax)

                # Throttle Y-axis autoscale — only update occasionally
                self._rr_autoscale_counter = (self._rr_autoscale_counter + 1) % 10
                if self._rr_autoscale_counter == 0:
                    self.plot_ax.relim()
                    self.plot_ax.autoscale_view(scalex=False, scaley=True)

            # Non-blocking redraw
            self.plot_canvas.draw_idle()
        except Exception:
            pass  # Silently ignore plot update errors

    @QtCore.pyqtSlot()
    def _on_rr_finished(self):
        """Handle RR Mode worker finished signal"""
        self.rr_worker = None
        self.btnDraw.setText("Plot (RR)")
        self.btnDraw.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}")

    def _update_plot(self):
        """Redraw the plot with current data"""
        try:
            for i, line in enumerate(self.plot_lines):
                times = self.plot_data[i]['time']
                values = self.plot_data[i]['value']
                line.set_data(times, values)

            # Only auto-scale if manual zoom is not active
            if not self.manual_zoom_active:
                self.plot_ax.relim()
                self.plot_ax.autoscale_view()

            self.plot_canvas.draw()
        except Exception as e:
            pass  # Silently ignore plot update errors

    # FIXED: Override Home button to auto-fit current data instead of restoring original view
    def _on_home_clicked(self):
        """Reset view to auto-fit current data safely, even if no data is present."""
        try:
            self.manual_zoom_active = False
            self.zoom_history.clear()

            # Re-enable autoscale (manually disabled after set_xlim/set_ylim)
            self.plot_ax.set_autoscalex_on(True)
            self.plot_ax.set_autoscaley_on(True)

            # Recalculate limits based on visible lines
            self.plot_ax.relim(visible_only=True)

            # Check if any channel has valid data
            has_data = any(
                len(self.plot_data[i]["time"]) > 0 and len(self.plot_data[i]["value"]) > 0
                for i in range(4)
            )

            if has_data:
                # Normal case: auto-fit to data
                self.plot_ax.autoscale_view()
            else:
                # Empty plot: set safe default window
                self.plot_ax.set_xlim(0, 10)
                self.plot_ax.set_ylim(-10, 10)

            # Update toolbar state and redraw
            if hasattr(self, "plot_toolbar") and self.plot_toolbar is not None:
                self.plot_toolbar.push_current()

            self.plot_canvas.draw_idle()
            self._set_status("View reset to auto-fit current data")
        except Exception as e:
            self._set_status(f"Home reset failed: {e}")

    # ---------- Close ----------
    def closeEvent(self, e: QtGui.QCloseEvent):
        """Handle window close event"""
        try:
            if self.worker:
                self._stop_polling()
            if self.plot_worker:
                self._stop_plotting()
            if self.rr_worker:
                self._stop_rr_mode()
            if self.serial_mgr.connected:
                self.serial_mgr.disconnect_port()
        except Exception:
            pass
        super().closeEvent(e)


# ==================== Windows AppUserModelID & Resource Path ====================
# Ensure Windows taskbar uses the app's own group and icon
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("yc.monitor.app.v1")
except Exception:
    pass  # Safe to ignore on non-Windows systems

# Universal resource loader for PyInstaller (_MEIPASS)
def resource_path(rel_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    base = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base, rel_path)


# ==================== Entry ====================
def main():
    """Application entry point"""
    app = QtWidgets.QApplication(sys.argv)

    # Qt palette with 4-color theme
    app.setStyle("Fusion")
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(Colors.BG_APP))               # Main window background
    palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(Colors.TEXT_PRIMARY))     # Main window text
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(Colors.BG_INPUT))               # Input base color
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(Colors.BG_PANEL))      # Alternate base
    palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(Colors.BG_PANEL))        # Tooltip background
    palette.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(Colors.TEXT_PRIMARY))    # Tooltip text
    palette.setColor(QtGui.QPalette.Text, QtGui.QColor(Colors.TEXT_PRIMARY))           # Text in inputs
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(Colors.BTN_PRIMARY_BG))       # Button background
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(Colors.BTN_PRIMARY_TEXT)) # Button text

    palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor(Colors.STATUS_ERROR))     # Error text
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(Colors.SOFT_YELLOW))       # Selection highlight
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(Colors.MIDNIGHT_NAVY))# Selected text on yellow
    app.setPalette(palette)

    # Try to register bundled Nunito fonts if available
    try:
        fonts_dir = Path(os.path.join(os.path.dirname(__file__), 'assets', 'fonts'))
        for fname in [
            'Nunito-Regular.ttf',
            'Nunito-SemiBold.ttf',
            'Nunito-Bold.ttf',
        ]:
            fpath = fonts_dir / fname
            if fpath.exists():
                QtGui.QFontDatabase.addApplicationFont(str(fpath))
        app.setFont(QtGui.QFont('Nunito'))
    except Exception:
        # Safe fallback: rely on system-installed fonts or stylesheet
        pass

    # Global stylesheet for cohesive dark theme and prettier widgets
    app.setStyleSheet(
        f"""
        QWidget {{
            background-color: {Colors.COOL_GRAY};
            color: {Colors.TEXT_PRIMARY};
            font-family: Nunito, Segoe UI, Arial, Helvetica, sans-serif;
            font-size: 14px;
        }}

        /* Panels */
        QFrame {{
            background-color: {Colors.BG_PANEL};
            border: 1px solid {Colors.BORDER_PANEL};
            border-radius: 10px;
        }}

        /* Inputs */
        QLineEdit, QComboBox {{
            background-color: {Colors.BG_INPUT};
            color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.BORDER_NORMAL};
            border-radius: 6px;
            padding: 6px 8px;
            selection-background-color: {Colors.SOFT_YELLOW};
            selection-color: {Colors.MIDNIGHT_NAVY};
        }}
        QLineEdit:focus, QComboBox:focus {{ border: 1px solid {Colors.BORDER_FOCUS}; }}
        QComboBox QAbstractItemView {{
            background: {Colors.BG_PANEL};
            color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.BORDER_NORMAL};
            selection-background-color: {Colors.SOFT_YELLOW};
            selection-color: {Colors.MIDNIGHT_NAVY};
        }}

        /* Buttons */
        QPushButton {{
            background-color: {Colors.BTN_PRIMARY_BG};
            color: {Colors.BTN_PRIMARY_TEXT};
            font-weight: 700;
            border: 1px solid {Colors.BORDER_NORMAL};
            border-radius: 8px;
            padding: 8px 12px;
        }}
        QPushButton:hover {{
            background-color: {Colors.AKAKUCHIBA};
            border-color: {Colors.BORDER_FOCUS};
        }}
        QPushButton:pressed {{
            background-color: {Colors.BTN_PRIMARY_BG};
            border-color: {Colors.BORDER_NORMAL};
        }}

        /* Header */
        QToolTip {{
            background-color: {Colors.BG_PANEL};
            color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.BORDER_NORMAL};
        }}

        /* Status bar */
        QStatusBar {{
            background: {Colors.BG_PANEL};
            color: {Colors.TEXT_PRIMARY};
            border-top: 1px solid {Colors.BORDER_PANEL};
        }}
        """
    )

    # Load and set application icon (works with PyInstaller)
    ico_path = resource_path("icon/Icon_Monitor_App.ico")
    app.setWindowIcon(QIcon(ico_path))  # Global app icon

    # Compute UI scale and initialize responsive tokens
    scale = compute_ui_scale(app)

    # RESPONSIVE: Create MainWindow with computed scale for responsive UI
    # The scale is passed to __init__ which initializes UiTokens before _build_ui is called
    w = MainWindow(ui_scale=scale)
    w.setWindowIcon(QIcon(ico_path))  # Set on the main window too
    w.ui_scale = scale  # Store scale for plot scaling if needed

    w.show()

    # After showing, adjust window size based on screen resolution
    # The layout has determined its minimum size, now we scale appropriately
    screen = app.primaryScreen()
    geom = screen.availableGeometry()
    sw, sh = geom.width(), geom.height()

    # Get the minimum size determined by the layout
    min_size = w.minimumSizeHint()
    layout_min_width = min_size.width()
    layout_min_height = min_size.height()

    # Calculate target size based on screen, but respect layout minimum
    if sw <= 1920:
        # Smaller screens (1920x1080): try to use 80% screen width, 70% height
        target_width = max(layout_min_width, int(sw * 0.80))
        target_height = max(layout_min_height, int(sh * 0.70))
    else:
        # Larger screens (2560x1440+): use 65% screen width, 65% height
        target_width = max(layout_min_width, int(sw * 0.65))
        target_height = max(layout_min_height, int(sh * 0.65))

    # Clamp to reasonable maximum to prevent oversized windows
    target_width = min(target_width, 1800)
    target_height = min(target_height, 1050)

    w.resize(target_width, target_height)

    # Center window on primary screen
    w.center_on_screen()

    # Display initial window size in status bar
    w._update_window_size_display()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()



