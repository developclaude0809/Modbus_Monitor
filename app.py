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

# ---------- pyserial ----------
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.exit("Missing pyserial. Please install: pip install pyserial")


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


# ==================== UI Helpers ====================
class SearchableCombo(QtWidgets.QComboBox):
    """QComboBox with type-to-search (contains) and mouse wheel support - EDITABLE"""

    def __init__(self, parent=None, half_width=True):
        super().__init__(parent)
        self.setEditable(True)
        # Enable mouse wheel support with strong focus and hover tracking
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.view().installEventFilter(self)

        # Completer for searching
        self._completer = QtWidgets.QCompleter(self)
        self._completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self._completer.setFilterMode(QtCore.Qt.MatchContains)
        self.setCompleter(self._completer)

        # Set width to half if requested
        if half_width:
            self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
            self.setMaximumWidth(150)

        # Hover state for scroll-on-hover
        self._hovered = False

        # Unify ComboBox visuals with right-side inputs (with visible borders)
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

    def setModel(self, model):
        """Override setModel to update completer"""
        super().setModel(model)
        self._completer.setModel(model)

    def enterEvent(self, event: QtCore.QEvent):
        self._hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent):
        self._hovered = False
        super().leaveEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent):
        # Scroll items when hovered or focused; do not open popup
        if self._hovered or self.hasFocus():
            cnt = self.count()
            if cnt > 0:
                delta = event.angleDelta().y()
                if delta > 0:
                    self.setCurrentIndex((self.currentIndex() - 1) % cnt)
                elif delta < 0:
                    self.setCurrentIndex((self.currentIndex() + 1) % cnt)
        else:
            event.ignore()


class AddressCombo(QtWidgets.QComboBox):
    """Deprecated: not used; preserved for backward compatibility."""
    pass


# ==================== Main Window ====================
class MainWindow(QtWidgets.QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modbus RTU Controller (PyQt5)")
        self.resize(1200, 780)

        self.serial_mgr = SerialManager(self)
        self.addr_items: List[str] = []  # ["000_name", ...]
        self.worker: Optional[PollWorker] = None

        self._build_ui()
        self._auto_load_definitions()
        self._refresh_ports()

    # ---------- UI Build ----------
    def _build_ui(self):
        """Build the user interface"""
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        layout = QtWidgets.QGridLayout(root)
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 0)
        layout.setRowStretch(1, 1)

        # Header
        header = QtWidgets.QWidget()
        header.setFixedHeight(50)  # Set specific height in pixels
        header.setStyleSheet(f"background:{Colors.COOL_GRAY}; border:none;")
        hbox = QtWidgets.QHBoxLayout(header)
        hbox.setContentsMargins(8, 4, 8, 4)
        title = QtWidgets.QLabel("Modbus RTU Controller")
        title.setStyleSheet(f"color:{Colors.TEXT_ON_DARK}; font-size:24px; font-weight:700; border:none;")
        hbox.addWidget(title)
        hbox.addStretch()


        # Left config panel
        left = QtWidgets.QFrame()
        left.setFrameShape(QtWidgets.QFrame.StyledPanel)
        left.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}} ")
        # Fix requested panel size
        left.setFixedSize(260, 650)
        left.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        v = QtWidgets.QVBoxLayout(left)
        # Internal padding for left frame
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        def row_widget(label_text: str, widget: QtWidgets.QWidget):
            row = QtWidgets.QWidget()
            rh = QtWidgets.QHBoxLayout(row)
            lab = QtWidgets.QLabel(label_text)
            lab.setMinimumWidth(110)
            lab.setAlignment(QtCore.Qt.AlignCenter)
            lab.setStyleSheet(f"font-weight:700; color:{Colors.TEXT_LABEL};")
            rh.addWidget(lab)
            rh.addWidget(widget, 1)
            v.addWidget(row)

        # Port
        self.cmbPort = SearchableCombo(half_width=True)
        row_widget("COM Port", self.cmbPort)

        # Baud
        self.cmbBaud = SearchableCombo(half_width=True)
        for b in ['1200','2400','4800','9600','19200','38400','57600','115200']:
            self.cmbBaud.addItem(b)
        self.cmbBaud.setCurrentText('9600')
        row_widget("Baud Rate", self.cmbBaud)

        # Data bits
        self.cmbDataBits = SearchableCombo(half_width=True)
        self.cmbDataBits.addItems(['7','8'])
        self.cmbDataBits.setCurrentText('8')
        row_widget("Data Bits", self.cmbDataBits)

        # Parity
        self.cmbParity = SearchableCombo(half_width=True)
        self.cmbParity.addItems(['None (N)', 'Even (E)', 'Odd (O)'])
        self.cmbParity.setCurrentText('None (N)')
        row_widget("Parity", self.cmbParity)

        # Stop bits
        self.cmbStopBits = SearchableCombo(half_width=True)
        self.cmbStopBits.addItems(['1','2'])
        self.cmbStopBits.setCurrentText('1')
        row_widget("Stop Bits", self.cmbStopBits)

        # Buttons
        # Row 1: Refresh and Connect side by side
        btnRow1 = QtWidgets.QWidget()
        btnRow1Layout = QtWidgets.QHBoxLayout(btnRow1)
        btnRow1Layout.setContentsMargins(0, 0, 0, 0)
        btnRow1Layout.setSpacing(8)

        self.btnRefreshPorts = QtWidgets.QPushButton("Refresh")
        self.btnRefreshPorts.setToolTip("Refresh COM ports")
        self.btnRefreshPorts.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_SECONDARY_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:10px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.BTN_SECONDARY_HOVER};}}"
        )
        self.btnRefreshPorts.clicked.connect(self._refresh_ports)
        btnRow1Layout.addWidget(self.btnRefreshPorts, 1)

        self.btnConnect = QtWidgets.QPushButton("Connect")
        self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.BTN_SUCCESS_HOVER};}}")
        self.btnConnect.clicked.connect(self._toggle_connection)
        btnRow1Layout.addWidget(self.btnConnect, 2)

        v.addWidget(btnRow1)

        v.addStretch()

        # Right monitor panel
        right = QtWidgets.QFrame()
        right.setFrameShape(QtWidgets.QFrame.StyledPanel)
        right.setStyleSheet(f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} QLabel{{color:{Colors.TEXT_LABEL};}}")
        # Fix requested panel size
        right.setFixedSize(680, 650)
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

        # Slave ID
        lblSlave = QtWidgets.QLabel("ID")
        lblSlave.setFixedWidth(LABEL_WIDTH)
        lblSlave.setAlignment(QtCore.Qt.AlignCenter)
        lblSlave.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        self.edSlave = QtWidgets.QLineEdit("1")
        self.edSlave.setValidator(QtGui.QIntValidator(1, 247, self))
        self.edSlave.setFixedWidth(INPUT_WIDTH)
        self.edSlave.setStyleSheet(f"background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; border:2px solid {Colors.BORDER_NORMAL}; padding:4px; border-radius:4px;")
        topLayout.addWidget(lblSlave)
        topLayout.addWidget(self.edSlave)

        # Timeout
        lblTimeout = QtWidgets.QLabel("Timeout")
        lblTimeout.setFixedWidth(LABEL_WIDTH)
        lblTimeout.setAlignment(QtCore.Qt.AlignCenter)
        lblTimeout.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        self.edTimeout = QtWidgets.QLineEdit("300")
        self.edTimeout.setValidator(QtGui.QIntValidator(1, 60000, self))
        self.edTimeout.setFixedWidth(INPUT_WIDTH)
        self.edTimeout.setStyleSheet(f"background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; border:2px solid {Colors.BORDER_NORMAL}; padding:4px; border-radius:4px;")
        topLayout.addWidget(lblTimeout)
        topLayout.addWidget(self.edTimeout)

        # Poll interval
        lblPoll = QtWidgets.QLabel("Poll")
        lblPoll.setFixedWidth(LABEL_WIDTH)
        lblPoll.setAlignment(QtCore.Qt.AlignCenter)
        lblPoll.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        self.edPoll = QtWidgets.QLineEdit("200")
        self.edPoll.setValidator(QtGui.QIntValidator(50, 600000, self))
        self.edPoll.setFixedWidth(INPUT_WIDTH)
        self.edPoll.setStyleSheet(f"background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; border:2px solid {Colors.BORDER_NORMAL}; padding:4px; border-radius:4px;")
        topLayout.addWidget(lblPoll)
        topLayout.addWidget(self.edPoll)

        topLayout.addStretch()

        # Load button
        self.btnLoad = QtWidgets.QPushButton("Load")
        self.btnLoad.setStyleSheet(f"QPushButton{{background:{Colors.BTN_SECONDARY_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:6px 12px; border:none; border-radius:6px;}} QPushButton:hover{{background:{Colors.BTN_SECONDARY_HOVER};}}")
        self.btnLoad.clicked.connect(self._load_definitions_dialog)
        topLayout.addWidget(self.btnLoad)

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
        grid.setColumnStretch(0, 1)

        self.rowCombos: List[SearchableCombo] = []
        self.rowValues: List[QtWidgets.QLabel] = []
        self.rowEdits:  List[QtWidgets.QLineEdit] = []

        for i in range(10):
            r = i
            # No numeric label column; start with the address selector
            combo = SearchableCombo()
            combo.addItem("---")
            # Use same styling as COM port - no custom arrow styling
            grid.addWidget(combo, r, 0)
            self.rowCombos.append(combo)

            val = QtWidgets.QLabel("----")
            val.setMinimumWidth(100)
            val.setStyleSheet(f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; padding:8px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; font-weight:600; font-size:16px;")
            grid.addWidget(val, r, 1)
            self.rowValues.append(val)

            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText("Enter value (0-65535)")
            edit.setValidator(QtGui.QIntValidator(0, 65535, self))
            edit.setStyleSheet(f"QLineEdit{{background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; border:2px solid {Colors.BORDER_NORMAL}; padding:6px; border-radius:4px;}} QLineEdit:focus{{border-color:{Colors.BORDER_FOCUS};}}")
            edit.setFixedWidth(120)
            edit.returnPressed.connect(lambda idx=i: self._write_register(idx))
            grid.addWidget(edit, r, 2)
            self.rowEdits.append(edit)

        grid.setRowStretch(10, 1)
        inner.setLayout(grid)
        scroll.setWidget(inner)
        rv.addWidget(scroll)

        # Status bar
        self.status = QtWidgets.QStatusBar()
        self.setStatusBar(self.status)
        self._set_status("Ready")

        # Layout place
        layout.addWidget(header, 0, 0, 1, 2)
        layout.addWidget(left,   1, 0)
        layout.addWidget(right,  1, 1)

        # Keep references for size reporting
        self.leftPanel = left
        self.rightPanel = right

    # ---------- Status ----------
    def _set_status(self, msg: str):
        """Update status bar"""
        self.status.showMessage(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def _report_panel_sizes(self):
        """Report left/right panel sizes to the status bar"""
        try:
            lw, lh = (self.leftPanel.width(), self.leftPanel.height()) if hasattr(self, 'leftPanel') else (0, 0)
            rw, rh = (self.rightPanel.width(), self.rightPanel.height()) if hasattr(self, 'rightPanel') else (0, 0)
            self._set_status(f"Left {lw}x{lh} | Right {rw}x{rh}")
        except Exception:
            pass

    def showEvent(self, e: QtGui.QShowEvent):
        super().showEvent(e)
        QtCore.QTimer.singleShot(0, self._report_panel_sizes)

    def resizeEvent(self, e: QtGui.QResizeEvent):
        super().resizeEvent(e)
        self._report_panel_sizes()

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
            timeout = int(self.edTimeout.text()) / 1000.0

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

            # Update all combo boxes
            for combo in self.rowCombos:
                combo.clear()
                combo.addItems(self.addr_items)
                if self.addr_items:
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
            self._start_polling()

    def _start_polling(self):
        """Start auto-polling"""
        if not self.serial_mgr.connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Please connect to a serial port first")
            return
        try:
            interval_ms = int(self.edPoll.text())
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
                timeout = int(self.edTimeout.text()) / 1000.0
                interval = int(self.edPoll.text()) / 1000.0
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
            timeout = int(self.edTimeout.text()) / 1000.0

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

    # ---------- Close ----------
    def closeEvent(self, e: QtGui.QCloseEvent):
        """Handle window close event"""
        try:
            if self.worker:
                self._stop_polling()
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
