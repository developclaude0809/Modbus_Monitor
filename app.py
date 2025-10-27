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
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Any, List
from dataclasses import dataclass

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

            # FIXED: Every 20 requests (not cycles), read 8 input registers (0x04) - 20:1 ratio
            if self._request_counter >= 20:
                self._request_counter = 0
                if self._running:
                    try:
                        req = ModbusRTU.read_input_registers(slave_id, 0x0000, 8)
                        ok, result = self.serial_mgr.transact(req, slave_id, 0x04, timeout=timeout)
                        if ok and isinstance(result, list) and len(result) == 8:
                            self.sigInputRegisters.emit(result, None)
                        else:
                            err = result if isinstance(result, str) else "Read failed"
                            self.sigInputRegisters.emit(None, err)
                            # FIXED: Emit explicit status message for timeouts
                            if "timeout" in str(err).lower():
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


# ==================== Main Window ====================
class MainWindow(QtWidgets.QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modbus RTU Controller")
        self.resize(1600, 900)

        self.serial_mgr = SerialManager(self)
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

        self._build_ui()
        self._auto_load_definitions()
        self._load_input_defs()  # Load 0x04 input register definitions
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
        self.btnLoad.setStyleSheet(f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}")
        self.btnLoad.clicked.connect(self._load_definitions_dialog)
        uart_layout.addWidget(self.btnLoad)

        # Refresh button
        self.btnRefreshPorts = QtWidgets.QPushButton("Refresh")
        self.btnRefreshPorts.setToolTip("Refresh COM ports")
        self.btnRefreshPorts.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}"
        )
        self.btnRefreshPorts.clicked.connect(self._refresh_ports)
        uart_layout.addWidget(self.btnRefreshPorts)

        # Connect button
        self.btnConnect = QtWidgets.QPushButton("Connect")
        self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}")
        self.btnConnect.clicked.connect(self._toggle_connection)
        uart_layout.addWidget(self.btnConnect)

        main_layout.addWidget(uart_panel)

        # ========== Motor Control Panel ==========
        motor_panel = QtWidgets.QFrame()
        motor_panel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        motor_panel.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        motor_panel.setFixedSize(650, 80)
        motor_panel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        motor_layout = QtWidgets.QHBoxLayout(motor_panel)
        motor_layout.setContentsMargins(12, 12, 12, 12)
        motor_layout.setSpacing(10)

        # Value input for motor control
        self.edMotorValue = QtWidgets.QLineEdit()
        self.edMotorValue.setText("0")
        self.edMotorValue.setValidator(QtGui.QIntValidator(0, 65535, self))
        self.edMotorValue.setFixedHeight(50)
        self.edMotorValue.setStyleSheet(
            f"QLineEdit{{background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; "
            f"border:2px solid {Colors.BORDER_NORMAL}; padding:6px; border-radius:4px; font-size:24px; font-weight:700;}} "
            f"QLineEdit:focus{{border-color:{Colors.BORDER_FOCUS};}}"
        )
        self.edMotorValue.returnPressed.connect(self._send_motor_value)
        motor_layout.addWidget(self.edMotorValue)

        # Send button (success style)
        self.btnMotorSend = QtWidgets.QPushButton("Send")
        self.btnMotorSend.setFixedWidth(120)
        self.btnMotorSend.setFixedHeight(50)
        self.btnMotorSend.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:600; font-size:26px; padding:8px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}"
        )
        self.btnMotorSend.clicked.connect(self._send_motor_value)
        motor_layout.addWidget(self.btnMotorSend)

        # Stop button (danger style)
        self.btnMotorStop = QtWidgets.QPushButton("Stop")
        self.btnMotorStop.setFixedWidth(120)
        self.btnMotorStop.setFixedHeight(50)
        self.btnMotorStop.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:600; font-size:26px; padding:8px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}"
        )
        self.btnMotorStop.clicked.connect(self._stop_motor)
        motor_layout.addWidget(self.btnMotorStop)

        # ========== Read Addresses Panel ==========
        RWpanel = QtWidgets.QFrame()
        RWpanel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        RWpanel.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        # Fix requested panel size (increased to fit all content without scroll)
        RWpanel.setFixedSize(650, 800)
        RWpanel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        rv = QtWidgets.QVBoxLayout(RWpanel)
        # Internal padding for right frame
        rv.setContentsMargins(3, 1, 3, 1)
        rv.setSpacing(0)  # No spacing - widgets will touch each other vertically

        # Top row: Start button, ID, Timeout, Poll Interval in horizontal layout
        topRow = QtWidgets.QWidget()
        topLayout = QtWidgets.QHBoxLayout(topRow)
        topLayout.setSpacing(0)
        topLayout.setContentsMargins(6, 0, 6, 0)

        # Start/Stop Polling button
        self.btnPolling = QtWidgets.QPushButton("Start")
        self.btnPolling.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}")
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
        grid = QtWidgets.QGridLayout(gridWidget)
        # Internal padding and spacing inside the register grid
        grid.setContentsMargins(5, 5, 5, 5)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(15)  # Increased from 10 to 15 for taller grid
        # Column stretch ratio: address_list : read_value : enter_value = 10 : 5 : 5
        grid.setColumnStretch(0, 10)
        grid.setColumnStretch(1, 5)
        grid.setColumnStretch(2, 5)

        self.rowCombos: List[SearchableCombo] = []
        self.rowValues: List[QtWidgets.QLabel] = []
        self.rowEdits:  List[QtWidgets.QLineEdit] = []

        for i in range(10):
            r = i
            # No numeric label column; start with the address selector
            combo = SearchableCombo(half_width=False)
            combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            combo.addItem("---")
            # Use same styling as COM port - no custom arrow styling
            grid.addWidget(combo, r, 0)
            self.rowCombos.append(combo)

            val = QtWidgets.QLabel("----")
            val.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            val.setStyleSheet(f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; padding:6px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; font-weight:600; font-size:14px;")
            grid.addWidget(val, r, 1)
            self.rowValues.append(val)

            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText("Enter value (0-65535)")
            edit.setValidator(QtGui.QIntValidator(0, 65535, self))
            edit.setStyleSheet(f"QLineEdit{{background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; border:2px solid {Colors.BORDER_NORMAL}; padding:4px; border-radius:4px;}} QLineEdit:focus{{border-color:{Colors.BORDER_FOCUS};}}")
            edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            edit.returnPressed.connect(lambda idx=i: self._write_register(idx))
            grid.addWidget(edit, r, 2)
            self.rowEdits.append(edit)

        rv.addWidget(gridWidget)

        # Input Register Display (FC 0x04)
        inputRegFrame = QtWidgets.QFrame()
        inputRegFrame.setFixedHeight(230)
        inputRegFrame.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:2px solid {Colors.BORDER_PANEL}; border-radius:6px;}}")

        # Create grid layout with 4 rows | 2 columns
        inputGrid = QtWidgets.QGridLayout(inputRegFrame)
        inputGrid.setContentsMargins(12, 12, 12, 12)
        inputGrid.setHorizontalSpacing(8)
        inputGrid.setVerticalSpacing(16)

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

        rv.addWidget(inputRegFrame)

        # Status bar
        self.status = QtWidgets.QStatusBar()
        self.setStatusBar(self.status)
        self._set_status("Ready")

        # region === RD Panel (Special Command Buttons) ===
        RDpanel = QtWidgets.QFrame()
        RDpanel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        RDpanel.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        RDpanel.setFixedHeight(80)
        RDpanel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        rd_layout = QtWidgets.QHBoxLayout(RDpanel)
        rd_layout.setContentsMargins(80, 1, 50, 1)
        rd_layout.setSpacing(15)

        # Normal button
        self.btnNormal = QtWidgets.QPushButton("Normal")
        self.btnNormal.setFixedWidth(120)
        self.btnNormal.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:25px; padding:5px 5px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}"
        )
        self.btnNormal.clicked.connect(lambda: self._send_rd_command("014600070001020000", "Normal"))
        rd_layout.addWidget(self.btnNormal)

        # Bypass button
        self.btnBypass = QtWidgets.QPushButton("Bypass")
        self.btnBypass.setFixedWidth(120)
        self.btnBypass.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:25px; padding:5px 5px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}"
        )
        self.btnBypass.clicked.connect(lambda: self._send_rd_command("014600070001022308", "Bypass"))
        rd_layout.addWidget(self.btnBypass)

        # List combobox
        self.rdCombo = SearchableCombo(half_width=False)
        self.rdCombo.addItems(["Inverter", "Converter", "Gsensor"])
        self.rdCombo.setStyleSheet(f"""
            QComboBox {{
                font-size: 22px;
                font-weight: 600;
                padding: 8px;
            }}
            QComboBox QAbstractItemView {{
                font-size: 20px;
            }}
        """)
        self.rdCombo.setFixedWidth(140)
        rd_layout.addWidget(self.rdCombo)

        # Switch button
        self.btnSwitch = QtWidgets.QPushButton("Switch")
        self.btnSwitch.setFixedWidth(120)
        self.btnSwitch.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:25px; padding:5px 5px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}"
        )
        self.btnSwitch.clicked.connect(self._send_switch_command)
        rd_layout.addWidget(self.btnSwitch)

        rd_layout.addStretch()  # Push controls to the left
        # endregion

        # region === Reset Panel (Special Reset Buttons) ===
        ResetPanel = QtWidgets.QFrame()
        ResetPanel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        ResetPanel.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        ResetPanel.setFixedSize(200, 80)
        ResetPanel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        reset_layout = QtWidgets.QVBoxLayout(ResetPanel)
        reset_layout.setContentsMargins(8, 8, 8, 8)
        reset_layout.setSpacing(8)

        # Reset button
        self.btnReset = QtWidgets.QPushButton("Reset")
        self.btnReset.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:14px; padding:6px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}"
        )
        self.btnReset.clicked.connect(lambda: self._send_reset_command("010601040001", "Reset"))
        reset_layout.addWidget(self.btnReset)

        # Reset Def button
        self.btnResetDef = QtWidgets.QPushButton("Reset Def")
        self.btnResetDef.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:14px; padding:6px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}"
        )
        self.btnResetDef.clicked.connect(lambda: self._send_reset_command("010601040002", "Reset Def"))
        reset_layout.addWidget(self.btnResetDef)
        # endregion

        # Plot panel
        plot_panel = QtWidgets.QFrame()
        plot_panel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        plot_panel.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        # Height adjusted: Right column = RD Panel(80) + gap(8) + Plot(800) = 888px to match left column (Motor 80 + gap 8 + RWpanel 800)
        plot_panel.setFixedHeight(800)
        plot_panel.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
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

        # Draw button
        self.btnDraw = QtWidgets.QPushButton("Draw")
        self.btnDraw.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}")
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
            line, = self.plot_ax.plot([], [], label=f'Ch{i+1}', color=color, linewidth=2)
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
        status_parts = [f"Probe @ {x_probe:.3f}s"]

        for i in range(4):
            # Check if channel is active (enabled for plotting)
            if not self.plot_active[i]:
                self._set_probe_label(i, "OFF", active=False)
                continue

            times = self.plot_data[i]['time']
            values = self.plot_data[i]['value']

            if not times:
                status_parts.append(f"CH{i+1}=N/A")
                self._set_probe_label(i, "N/A", active=False)
                continue

            # Find nearest time index
            idx = self._nearest_index(times, x_probe)
            if idx is None:
                status_parts.append(f"CH{i+1}=N/A")
                self._set_probe_label(i, "N/A", active=False)
                continue

            # Get the value at that index
            y_val = values[idx]
            x_val = times[idx]

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
            self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.ROSE_CORAL};}}")
        else:
            self.btnConnect.setText("Connect")
            self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}")

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
            self._set_status("Disconnected")
        except Exception as e:
            self._set_status(f"Disconnect error: {e}")

    # ---------- Address Definitions ----------
    def _auto_load_definitions(self):
        """Auto-load address definitions from default path"""
        try:
            default_path = Path('./setting/address_def.ddata')
            if default_path.exists():
                self._load_definitions_file(str(default_path))
        except Exception:
            pass

    def _load_input_defs(self):
        """Load 0x04 input register definitions from __address_04def.ddata"""
        # Initialize with defaults for all 8 input registers
        self.input_defs = [InputRegDef.create_default(i) for i in range(8)]

        try:
            def_path = Path('./setting/__address_04def.ddata')
            if not def_path.exists():
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

    def _update_input_titles(self):
        """Update input register title labels from loaded definitions"""
        if not hasattr(self, 'input_defs') or not hasattr(self, 'inputRegLabels'):
            return

        for i in range(min(8, len(self.input_defs), len(self.inputRegLabels))):
            self.inputRegLabels[i].setText(self.input_defs[i].title)

    def _load_definitions_dialog(self):
        """Show file dialog to load address definitions"""
        start_dir = os.path.dirname(os.path.abspath(sys.argv[0])) if getattr(sys, 'frozen', False) else os.getcwd()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Address Definition File", start_dir,
            "Data files (*.ddata);;Text files (*.txt);;All files (*.*)"
        )
        if path:
            self._load_definitions_file(path)

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

            # Clear on success per spec
            self.edMotorValue.clear()
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

            self._set_status(f"Switch command sent: {selected} → ID set to {new_id}")
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
            self.worker.sigStatus.connect(self._set_status)
            self.worker.start()

            self.btnPolling.setText("Stop")
            self.btnPolling.setStyleSheet(f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.ROSE_CORAL};}}")
            self._set_status("Polling started")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            self._set_status(f"Failed to start polling: {e}")

    def _stop_polling(self):
        """Stop auto-polling"""
        if self.worker:
            self.worker.stop()
            self.worker.wait(1500)
            self.worker = None
        # Reset input register displays
        for i in range(8):
            self.inputRegValues[i].setText("----")
            self.inputRegValues[i].setStyleSheet(
                f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; "
                f"padding:6px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; "
                f"font-weight:600; font-size:14px;"
            )
        self.btnPolling.setText("Start")
        self.btnPolling.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}")
        self._set_status("Polling stopped")

    @QtCore.pyqtSlot(int, object, object)
    def _on_register_update(self, index: int, value: Optional[int], error: Optional[str]):
        """Update register display from polling thread"""
        if value is not None:
            self.rowValues[index].setText(str(value))
            self.rowValues[index].setStyleSheet(f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; padding:8px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; font-weight:600; font-size:16px;")
        else:
            text = "Timeout" if (error and "timeout" in error.lower()) else "ERR"
            self.rowValues[index].setText(text)
            self.rowValues[index].setStyleSheet(f"color:{Colors.STATUS_ERROR}; background:{Colors.BG_PANEL}; padding:8px; border:2px solid {Colors.STATUS_ERROR}; border-radius:4px; font-weight:600; font-size:16px;")

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
        if not hasattr(self, 'inputRegValues') or len(self.inputRegValues) != 8:
            return

        try:  # FIXED: Wrap in try-except to catch widget deletion race
            # FIXED: Added isinstance(values, list) check to prevent TypeError
            if values is not None and isinstance(values, list) and len(values) == 8:
                for i, val in enumerate(values):
                    # Use custom rendering based on definition file
                    rendered_text = self._render_input04(i, val)
                    self.inputRegValues[i].setText(rendered_text)
                    self.inputRegValues[i].setStyleSheet(
                        f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; "
                        f"padding:6px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; "
                        f"font-weight:600; font-size:14px;"
                    )
            else:
                # Error case
                for i in range(8):
                    text = "Timeout" if (error and "timeout" in error.lower()) else "ERR"
                    self.inputRegValues[i].setText(text)
                    self.inputRegValues[i].setStyleSheet(
                        f"color:{Colors.STATUS_ERROR}; background:{Colors.BG_PANEL}; "
                        f"padding:6px; border:2px solid {Colors.STATUS_ERROR}; border-radius:4px; "
                        f"font-weight:600; font-size:14px;"
                    )
        except (RuntimeError, AttributeError):
            # FIXED: Widget was deleted during update, exit gracefully
            return

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

            self.rowEdits[index].clear()
            self.rowValues[index].setText(str(shown))
            self.rowValues[index].setStyleSheet(f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; padding:8px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; font-weight:600; font-size:16px;")
            self._set_status(f"Write successful: Address {addr} = {shown}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Write Error", str(e))
            self._set_status(f"Write failed: {e}")

    # ---------- Plotting ----------
    def _toggle_plotting(self):
        """Toggle real-time plotting"""
        if self.plot_worker and self.plot_worker.isRunning():
            self._stop_plotting()
        else:
            self._start_plotting()

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
            self.plot_worker.sigStatus.connect(self._set_status)
            self.plot_worker.start()

            self.btnDraw.setText("Stop")
            self.btnDraw.setStyleSheet(f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.ROSE_CORAL};}}")
            self._set_status("Plotting started")

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
        self.btnDraw.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.AKAKUCHIBA};}}")
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

    w = MainWindow()
    w.setWindowIcon(QIcon(ico_path))  # Set on the main window too
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()



