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
from pathlib import Path
from typing import Optional, Tuple, Any, List

from PyQt5 import QtCore, QtGui, QtWidgets

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
    from matplotlib.figure import Figure
    import matplotlib.pyplot as plt
except ImportError:
    sys.exit("Missing matplotlib. Please install: pip install matplotlib")


# ==================== COLOR CONFIGURATION ====================
# Unified color palette sorted by RGB order for easy modification

class Colors:
    # ------------------------------------------------------------
    # 🎨 MASTER COLOR PALETTE (Sorted by RGB hex values)
    # ------------------------------------------------------------
    BTN_DANGER_BG     = "#A32424"
    BTN_SUCCESS_HOVER = "#10B97B"
    BTN_SUCCESS_BG    = "#059661"
    MIDNIGHT_NAVY     = "#0F172A"
    DEEP_BLUE         = "#2563EB"
    COOL_GRAY         = "#1E293B"
    SKY_BLUE          = "#60A5FA"
    MIST_BLUE         = "#38BDF8"
    MINT_GLOW         = "#34D399"
    SOFT_YELLOW       = "#F4F27E"
    CREAM_TINT        = "#FFF5C2"
    ROSE_CORAL        = "#F87171"
    BG_INPUT          = "#334155"
    BTN_TEXT_COLOR    = "#FFFFFF"

    # ------------------------------------------------------------
    # 🌑 SEMANTIC COLORS — Contextual mapping for dark UI
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

        if func == 0x06:
            if len(response) != 8:
                return False, f"Write response length mismatch: {len(response)}"
            addr, value = struct.unpack(">HH", response[2:6])
            return True, (addr, value)

        # fallback raw
        return True, response[2:-2]


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

    def _expected_response_length(self, func: int, buf: bytearray) -> int:
        """Calculate expected response length"""
        if func == 0x06:
            return 8
        if func == 0x03:
            if len(buf) >= 3:
                return 5 + buf[2]
            return 0
        return 0

    def transact(self, request: bytes, expected_slave: int, expected_func: int,
                 timeout: float = 0.5) -> Tuple[bool, Any]:
        """Perform Modbus transaction with automatic retries"""
        with QtCore.QMutexLocker(self._lock):
            if not self.connected or not self.port:
                return False, "Not connected"

        # do IO outside of lock but keep port ref
        port = self.port
        if port is None:
            return False, "Not connected"

        for attempt in range(self.max_retries):
            try:
                time.sleep(self.inter_frame_delay)

                port.reset_input_buffer()
                port.reset_output_buffer()
                port.write(request)
                port.flush()

                start = time.time()
                buf = bytearray()
                expected_len = 0

                while (time.time() - start) < timeout:
                    chunk = port.read(256)
                    if chunk:
                        buf.extend(chunk)
                        if len(buf) >= 2:
                            expected_len = self._expected_response_length(expected_func, buf)
                        if expected_len and len(buf) >= expected_len:
                            break
                    else:
                        time.sleep(0.003)

                if not buf:
                    if attempt < self.max_retries - 1:
                        time.sleep(0.05)
                        continue
                    return False, "Timeout - No response"

                if expected_len and len(buf) < expected_len:
                    if attempt < self.max_retries - 1:
                        time.sleep(0.05)
                        continue
                    return False, f"Incomplete response ({len(buf)}/{expected_len} bytes)"

                return ModbusRTU.parse_response(bytes(buf), expected_slave, expected_func)

            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(0.05)
                    continue
                return False, str(e)

        return False, "Max retries exceeded"


# ==================== Polling Worker ====================
class PollWorker(QtCore.QThread):
    """Background thread for auto-polling registers"""

    sigRegister = QtCore.pyqtSignal(int, object, object)  # index, value|None, error|None
    sigStatus = QtCore.pyqtSignal(str)

    def __init__(self, serial_mgr: SerialManager, get_row_addr_callable, get_cfg_callable, parent=None):
        super().__init__(parent)
        self.serial_mgr = serial_mgr
        self.get_row_addr = get_row_addr_callable  # returns addr int or None for row
        self.get_cfg = get_cfg_callable            # returns (slave_id:int, timeout:float, interval:float)
        self._running = True

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

                except Exception as e:
                    self.sigRegister.emit(i, None, str(e))

            time.sleep(interval)


# ==================== Plot Worker ====================
class PlotWorker(QtCore.QThread):
    """Background thread for plotting with phase-locked 40ms requests.

    Reads 4 channels (addresses 0x0001..0x0004) at a fixed request interval,
    keeping each slot aligned to a 40ms grid (or configurable via req_interval_ms).
    One full cycle across the four channels takes exactly 4 * req_interval_ms.
    """

    sigData = QtCore.pyqtSignal(int, object, object)  # channel_index, value|None, timestamp|None
    sigStatus = QtCore.pyqtSignal(str)

    def __init__(self, serial_mgr: SerialManager, get_addresses_callable, get_cfg_callable, parent=None, req_interval_ms: int = 40):
        super().__init__(parent)
        self.serial_mgr = serial_mgr
        # Kept for compatibility; not used since addresses are fixed 0x0001..0x0004
        self.get_addresses = get_addresses_callable
        self.get_cfg = get_cfg_callable              # returns (slave_id:int, timeout:float)
        self.req_interval_ms = max(1, int(req_interval_ms))
        self._running = True

    def stop(self):
        """Stop the plot worker thread"""
        self._running = False

    def run(self):
        """Phase-locked acquisition: CH1..CH4 on a 40ms grid (160ms per cycle)."""
        # Use a high-resolution monotonic clock for scheduling
        interval_s = self.req_interval_ms / 1000.0
        base = time.perf_counter()
        slot_idx = 0  # increases every request; channel = slot_idx % 4

        # Fixed Modbus addresses for CH1..CH4
        fixed_addresses = [0x0001, 0x0002, 0x0003, 0x0004]

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

            # Determine channel and address
            ch = slot_idx % 4
            addr = fixed_addresses[ch]

            # Timestamp for UI
            timestamp = time.time()

            # Perform Modbus read for this channel
            try:
                req = ModbusRTU.read_holding_registers(slave_id, addr, 1)
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


# ==================== Main Window ====================
class MainWindow(QtWidgets.QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modbus RTU Controller (PyQt5)")
        self.resize(1400, 750)

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

        self._build_ui()
        self._auto_load_definitions()
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

        # Refresh button
        self.btnRefreshPorts = QtWidgets.QPushButton("Refresh")
        self.btnRefreshPorts.setToolTip("Refresh COM ports")
        self.btnRefreshPorts.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_SECONDARY_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.BTN_SECONDARY_HOVER};}}"
        )
        self.btnRefreshPorts.clicked.connect(self._refresh_ports)
        uart_layout.addWidget(self.btnRefreshPorts)

        # Connect button
        self.btnConnect = QtWidgets.QPushButton("Connect")
        self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 16px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.BTN_SUCCESS_HOVER};}}")
        self.btnConnect.clicked.connect(self._toggle_connection)
        uart_layout.addWidget(self.btnConnect)

        main_layout.addWidget(uart_panel)

        # Read Addresses Panel (left side of bottom layout)
        right = QtWidgets.QFrame()
        right.setFrameShape(QtWidgets.QFrame.StyledPanel)
        right.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        # Fix requested panel size
        right.setFixedSize(500, 650)
        right.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        rv = QtWidgets.QVBoxLayout(right)
        # Internal padding for right frame
        rv.setContentsMargins(12, 12, 12, 12)
        rv.setSpacing(10)

        # Top row: Start button, ID, Timeout, Poll Interval in horizontal layout
        topRow = QtWidgets.QWidget()
        topLayout = QtWidgets.QHBoxLayout(topRow)
        topLayout.setSpacing(8)
        topLayout.setContentsMargins(8, 8, 8, 4)

        # Start/Stop Polling button
        self.btnPolling = QtWidgets.QPushButton("Start")
        self.btnPolling.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.BTN_SUCCESS_HOVER};}}")
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

        # Scroll area with 10 rows
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(inner)
        # Internal padding and spacing inside the register grid
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
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
            val.setStyleSheet(f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; padding:8px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; font-weight:600; font-size:16px;")
            grid.addWidget(val, r, 1)
            self.rowValues.append(val)

            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText("Enter value (0-65535)")
            edit.setValidator(QtGui.QIntValidator(0, 65535, self))
            edit.setStyleSheet(f"QLineEdit{{background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; border:2px solid {Colors.BORDER_NORMAL}; padding:6px; border-radius:4px;}} QLineEdit:focus{{border-color:{Colors.BORDER_FOCUS};}}")
            edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            edit.returnPressed.connect(lambda idx=i: self._write_register(idx))
            grid.addWidget(edit, r, 2)
            self.rowEdits.append(edit)

        grid.setRowStretch(10, 1)
        inner.setLayout(grid)
        scroll.setWidget(inner)
        rv.addWidget(scroll)

        # Bottom-left Load button (below 10th row)
        bottomBar = QtWidgets.QHBoxLayout()
        bottomBar.setContentsMargins(0, 0, 0, 0)
        bottomBar.setSpacing(0)
        self.btnLoad = QtWidgets.QPushButton("Load")
        self.btnLoad.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SECONDARY_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:6px 12px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.BTN_SECONDARY_HOVER};}}")
        self.btnLoad.clicked.connect(self._load_definitions_dialog)
        bottomBar.addWidget(self.btnLoad)
        bottomBar.addStretch(1)
        rv.addLayout(bottomBar)

        # Status bar
        self.status = QtWidgets.QStatusBar()
        self.setStatusBar(self.status)
        self._set_status("Ready")

        # Plot panel
        plot_panel = QtWidgets.QFrame()
        plot_panel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        plot_panel.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        plot_panel.setFixedSize(860, 650)
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
        for i in range(4):
            lbl = QtWidgets.QLabel(f"Ch{i+1}")
            lbl.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            lbl.setFixedWidth(40)

            combo = SearchableCombo(half_width=False)
            combo.addItem("---")
            combo.setStyleSheet("font-size:12px; font-weight:500;")
            # Fit four label+combo pairs within the fixed panel width
            combo.setFixedWidth(160)
            combo.setFixedHeight(35)

            # Place all channels on the same row
            row = 0
            col = i * 2  # label at even col, combo at odd col
            addrLayout.addWidget(lbl, row, col)
            addrLayout.addWidget(combo, row, col + 1)
            self.plotCombos.append(combo)

        pv.addWidget(addrWidget)

        # Draw button
        self.btnDraw = QtWidgets.QPushButton("Draw")
        self.btnDraw.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.BTN_SUCCESS_HOVER};}}")
        # Keep the button compact instead of stretching across the panel
        self.btnDraw.setFixedHeight(40)
        self.btnDraw.setFixedWidth(250)
        self.btnDraw.clicked.connect(self._toggle_plotting)
        pv.addWidget(self.btnDraw, alignment=QtCore.Qt.AlignHCenter)

        # Matplotlib canvas
        self.plot_figure = Figure(figsize=(8, 5.5), dpi=100, facecolor=Colors.BG_PANEL)
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
        colors = [Colors.MIST_BLUE, Colors.MINT_GLOW, Colors.SOFT_YELLOW, Colors.ROSE_CORAL]
        for i, color in enumerate(colors):
            line, = self.plot_ax.plot([], [], label=f'Ch{i+1}', color=color, linewidth=2)
            self.plot_lines.append(line)
        self.plot_ax.legend(loc='upper left', facecolor=Colors.BG_PANEL, edgecolor=Colors.BORDER_NORMAL, labelcolor=Colors.TEXT_PRIMARY)

        pv.addWidget(self.plot_canvas)

        # Add all panels to main layout
        main_layout.addWidget(uart_panel)

        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.setSpacing(8)
        bottom_layout.addWidget(right)  # Read addresses panel on left
        bottom_layout.addWidget(plot_panel)  # Plot panel on right

        main_layout.addLayout(bottom_layout)

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
            self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.BTN_DANGER_HOVER};}}")
        else:
            self.btnConnect.setText("Connect")
            self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.BTN_SUCCESS_HOVER};}}")

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
            self.worker.sigStatus.connect(self._set_status)
            self.worker.start()

            self.btnPolling.setText("Stop")
            self.btnPolling.setStyleSheet(f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.BTN_DANGER_HOVER};}}")
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
        self.btnPolling.setText("Start")
        self.btnPolling.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.BTN_SUCCESS_HOVER};}}")
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
            ok, result = self.serial_mgr.transact(req, slave_id, 0x06, timeout=timeout)
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
            # Clear previous data
            for ch_data in self.plot_data:
                ch_data['time'].clear()
                ch_data['value'].clear()
            self.plot_start_time = time.time()

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

            def get_cfg():
                slave = int(self.edSlave.text())
                timeout = self.timeout_ms / 1000.0
                return slave, timeout

            self.plot_worker = PlotWorker(self.serial_mgr, get_addresses, get_cfg, self)
            self.plot_worker.sigData.connect(self._on_plot_data)
            self.plot_worker.sigStatus.connect(self._set_status)
            self.plot_worker.start()

            self.btnDraw.setText("Stop")
            self.btnDraw.setStyleSheet(f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.BTN_DANGER_HOVER};}}")
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
        self.btnDraw.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.BTN_SUCCESS_HOVER};}}")
        self._set_status("Plotting stopped")

    @QtCore.pyqtSlot(int, object, object)
    def _on_plot_data(self, channel: int, value: Optional[int], timestamp: Optional[float]):
        """Update plot with new data point"""
        if value is not None and timestamp is not None:
            # Store data
            elapsed = timestamp - self.plot_start_time
            self.plot_data[channel]['time'].append(elapsed)
            self.plot_data[channel]['value'].append(value)

            # Keep only last 100 points per channel
            if len(self.plot_data[channel]['time']) > 100:
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

            # Auto-scale axes
            self.plot_ax.relim()
            self.plot_ax.autoscale_view()

            self.plot_canvas.draw()
        except Exception as e:
            pass  # Silently ignore plot update errors

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
            background-color: {Colors.BTN_PRIMARY_HOVER};
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

    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
