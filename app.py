"""
Enhanced Modbus RTU Controller with PyQt5
- Modern, dark-themed 9-color UI design
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
# Easy to modify theme colors - just change these values!
class Colors:
    # Main theme colors (9 types - gradient from darkest to lightest)
    CR1 = "#0F185B"      # Darkest blue
    CR2 = "#1B288A"      # Dark blue
    CR3 = "#344CB9"      # Primary blue
    CR4 = "#5670D4"      # Medium-light blue
    CR5 = "#7894E8"      # Light blue
    CR6 = "#A8B9D7"      # Very light blue
    CR7 = "#C4D1B8"      # Transitional beige
    CR8 = "#D7C99A"      # Light gold/beige
    CR9 = "#F2E4C7"      # Lightest gold/cream

    # Semantic colors (based on theme)
    BACKGROUND_DARKEST = CR1     # Deepest background
    BACKGROUND_DARK = CR2        # Dark background
    BACKGROUND_MID = CR3         # Medium background
    BACKGROUND_LIGHT = CR4       # Light background
    BACKGROUND_LIGHTEST = CR5    # Lightest background

    TEXT_PRIMARY = CR9           # Primary text color (lightest)
    TEXT_SECONDARY = CR8         # Secondary text color
    TEXT_TERTIARY = CR7          # Tertiary text color
    TEXT_ACCENT = CR6            # Accent text color

    BORDER_DARK = CR2            # Dark borders
    BORDER_LIGHT = CR4           # Light borders
    BORDER_ACCENT = CR6          # Accent borders

    # Status colors
    SUCCESS = "#22c55e"          # Green for success
    ERROR = "#ef4444"            # Red for errors
    WARNING = "#f59e0b"          # Orange for warnings
    INFO = CR5                   # Info color (light blue)

    # Button colors
    BUTTON_CONNECT = SUCCESS
    BUTTON_DISCONNECT = ERROR
    BUTTON_PRIMARY = CR3         # Primary button
    BUTTON_SECONDARY = "#8b5cf6" # Purple
    BUTTON_HOVER = CR4           # Button hover state
# ========================================================


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
                self.sigStatus.emit(f"✗ Invalid configuration: {e}")
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        # Enable mouse wheel support with strong focus
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.view().installEventFilter(self)
        # Completer for searching
        self._completer = QtWidgets.QCompleter(self)
        self._completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self._completer.setFilterMode(QtCore.Qt.MatchContains)
        self.setCompleter(self._completer)

    def setModel(self, model):
        """Override setModel to update completer"""
        super().setModel(model)
        self._completer.setModel(model)

    def wheelEvent(self, e: QtGui.QWheelEvent):
        """Mouse wheel support - only when focused"""
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class AddressCombo(QtWidgets.QComboBox):
    """Drop-down only combo box for address selection with mouse wheel support"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # NOT editable - pure drop-down selection only
        self.setEditable(False)
        # Enable mouse wheel support with strong focus
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        # Make it scrollable with large lists
        self.setMaxVisibleItems(20)
        # Set size policy
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def wheelEvent(self, e: QtGui.QWheelEvent):
        """Mouse wheel support - scroll through addresses"""
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


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
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(1, 1)

        # Header
        header = QtWidgets.QWidget()
        header.setStyleSheet(f"background:{Colors.CR2}; border-bottom:2px solid {Colors.CR3};")
        hbox = QtWidgets.QHBoxLayout(header)
        title = QtWidgets.QLabel("🔧 Modbus RTU Controller")
        title.setStyleSheet(f"color:{Colors.CR9}; font-size:24px; font-weight:800;")
        hbox.addWidget(title)
        hbox.addStretch()

        self.lblConnDot = QtWidgets.QLabel("●")
        self.lblConnDot.setStyleSheet(f"color:{Colors.ERROR}; font-size:22px;")
        self.lblConn = QtWidgets.QLabel("Disconnected")
        self.lblConn.setStyleSheet(f"color:{Colors.CR9}; font-weight:600; background:{Colors.CR1}; padding:6px 12px; border-radius:4px; border:2px solid {Colors.CR4};")
        wrap = QtWidgets.QHBoxLayout()
        wrap.addWidget(self.lblConnDot)
        wrap.addWidget(self.lblConn)
        rightw = QtWidgets.QWidget()
        rightw.setLayout(wrap)
        hbox.addWidget(rightw)

        # Left config panel
        left = QtWidgets.QFrame()
        left.setFrameShape(QtWidgets.QFrame.StyledPanel)
        left.setStyleSheet(f"QFrame{{background:{Colors.CR1}; border:2px solid {Colors.CR3}; border-radius:10px;}} QLabel{{color:{Colors.CR9};}} ")
        v = QtWidgets.QVBoxLayout(left)
        v.setSpacing(4)  # Reduce spacing between fields (default is ~6-10)

        def row_widget(label_text: str, widget: QtWidgets.QWidget):
            row = QtWidgets.QWidget()
            rh = QtWidgets.QHBoxLayout(row)
            lab = QtWidgets.QLabel(label_text)
            lab.setMinimumWidth(110)
            lab.setStyleSheet("font-weight:700;")
            rh.addWidget(lab)
            rh.addWidget(widget, 1)
            v.addWidget(row)

        # Port
        self.cmbPort = SearchableCombo()
        row_widget("COM Port:", self.cmbPort)

        # Baud
        self.cmbBaud = SearchableCombo()
        for b in ['1200','2400','4800','9600','19200','38400','57600','115200']:
            self.cmbBaud.addItem(b)
        self.cmbBaud.setCurrentText('9600')
        row_widget("Baud Rate:", self.cmbBaud)

        # Data bits
        self.cmbDataBits = SearchableCombo()
        self.cmbDataBits.addItems(['7','8'])
        self.cmbDataBits.setCurrentText('8')
        row_widget("Data Bits:", self.cmbDataBits)

        # Parity
        self.cmbParity = SearchableCombo()
        self.cmbParity.addItems(['None (N)', 'Even (E)', 'Odd (O)'])
        self.cmbParity.setCurrentText('None (N)')
        row_widget("Parity:", self.cmbParity)

        # Stop bits
        self.cmbStopBits = SearchableCombo()
        self.cmbStopBits.addItems(['1','2'])
        self.cmbStopBits.setCurrentText('1')
        row_widget("Stop Bits:", self.cmbStopBits)

        # Timeout
        self.edTimeout = QtWidgets.QLineEdit("300")
        self.edTimeout.setValidator(QtGui.QIntValidator(1, 60000, self))
        row_widget("Timeout (ms):", self.edTimeout)

        # Slave ID
        self.edSlave = QtWidgets.QLineEdit("1")
        self.edSlave.setValidator(QtGui.QIntValidator(1, 247, self))
        row_widget("Slave ID:", self.edSlave)

        # Poll interval
        self.edPoll = QtWidgets.QLineEdit("200")
        self.edPoll.setValidator(QtGui.QIntValidator(50, 600000, self))
        row_widget("Poll Interval (ms):", self.edPoll)

        # Buttons
        self.btnConnect = QtWidgets.QPushButton("📡 Connect")
        self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BUTTON_CONNECT}; color:{Colors.CR9}; font-weight:700; padding:10px; border:2px solid {Colors.CR5}; border-radius:6px;}} QPushButton:hover{{background:#16a34a; border-color:{Colors.CR6};}}")
        self.btnConnect.clicked.connect(self._toggle_connection)
        v.addWidget(self.btnConnect)

        self.btnPolling = QtWidgets.QPushButton("▶️ Start Polling")
        self.btnPolling.setStyleSheet(f"QPushButton{{background:{Colors.CR3}; color:{Colors.CR9}; font-weight:700; padding:10px; border:2px solid {Colors.CR5}; border-radius:6px;}} QPushButton:hover{{background:{Colors.CR4}; border-color:{Colors.CR6};}}")
        self.btnPolling.clicked.connect(self._toggle_polling)
        v.addWidget(self.btnPolling)

        v.addStretch()

        # Right monitor panel
        right = QtWidgets.QFrame()
        right.setFrameShape(QtWidgets.QFrame.StyledPanel)
        right.setStyleSheet(f"QFrame{{background:{Colors.CR1}; border:2px solid {Colors.CR3}; border-radius:10px;}} QLabel{{color:{Colors.CR9};}}")
        rv = QtWidgets.QVBoxLayout(right)

        # Load button (no title header)
        headLayout = QtWidgets.QHBoxLayout()
        headLayout.addStretch()
        self.btnLoad = QtWidgets.QPushButton("Load Address File")
        self.btnLoad.setStyleSheet(f"QPushButton{{background:{Colors.BUTTON_SECONDARY}; color:{Colors.CR9}; font-weight:700; padding:6px 12px; border:2px solid {Colors.CR5}; border-radius:6px; margin:8px;}} QPushButton:hover{{background:#7c3aed; border-color:{Colors.CR6};}}")
        self.btnLoad.clicked.connect(self._load_definitions_dialog)
        headLayout.addWidget(self.btnLoad)
        rv.addLayout(headLayout)

        # Scroll area with 10 rows
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(inner)
        grid.setColumnStretch(1, 1)

        self.rowCombos: List[SearchableCombo] = []
        self.rowValues: List[QtWidgets.QLabel] = []
        self.rowEdits:  List[QtWidgets.QLineEdit] = []

        for i in range(10):
            r = i
            labNo = QtWidgets.QLabel(f"{i+1:02d}")
            labNo.setStyleSheet(f"color:{Colors.CR8}; background:{Colors.CR2}; padding:8px; border-radius:4px; font-weight:700;")
            grid.addWidget(labNo, r, 0)

            combo = SearchableCombo()
            combo.addItem("---")
            # Use same styling as COM port - no custom arrow styling
            grid.addWidget(combo, r, 1)
            self.rowCombos.append(combo)

            val = QtWidgets.QLabel("----")
            val.setMinimumWidth(100)
            val.setStyleSheet(f"color:{Colors.CR9}; background:{Colors.CR2}; padding:8px; border:2px solid {Colors.CR4}; border-radius:4px; font-weight:600; font-size:14px;")
            grid.addWidget(val, r, 2)
            self.rowValues.append(val)

            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText("Enter value (0-65535)")
            edit.setValidator(QtGui.QIntValidator(0, 65535, self))
            edit.setStyleSheet(f"QLineEdit{{background:{Colors.CR2}; color:{Colors.CR9}; border:2px solid {Colors.CR4}; padding:6px; border-radius:4px;}} QLineEdit:focus{{border-color:{Colors.CR5}; background:{Colors.CR3};}}")
            edit.returnPressed.connect(lambda idx=i: self._write_register(idx))
            grid.addWidget(edit, r, 3)
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

    # ---------- Status ----------
    def _set_status(self, msg: str):
        """Update status bar"""
        self.status.showMessage(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def _set_connected_ui(self, connected: bool):
        """Update UI for connection state"""
        if connected:
            self.lblConnDot.setStyleSheet(f"color:{Colors.SUCCESS}; font-size:22px;")
            self.lblConn.setText("Connected")
            self.lblConn.setStyleSheet(f"color:{Colors.CR9}; font-weight:600; background:{Colors.SUCCESS}; padding:6px 12px; border-radius:4px; border:2px solid {Colors.CR5};")
            self.btnConnect.setText("🔌 Disconnect")
            self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BUTTON_DISCONNECT}; color:{Colors.CR9}; font-weight:700; padding:10px; border:2px solid {Colors.CR5}; border-radius:6px;}} QPushButton:hover{{background:#dc2626; border-color:{Colors.CR6};}}")
        else:
            self.lblConnDot.setStyleSheet(f"color:{Colors.ERROR}; font-size:22px;")
            self.lblConn.setText("Disconnected")
            self.lblConn.setStyleSheet(f"color:{Colors.CR9}; font-weight:600; background:{Colors.CR1}; padding:6px 12px; border-radius:4px; border:2px solid {Colors.CR4};")
            self.btnConnect.setText("📡 Connect")
            self.btnConnect.setStyleSheet(f"QPushButton{{background:{Colors.BUTTON_CONNECT}; color:{Colors.CR9}; font-weight:700; padding:10px; border:2px solid {Colors.CR5}; border-radius:6px;}} QPushButton:hover{{background:#16a34a; border-color:{Colors.CR6};}}")

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
                self._set_status(f"✓ {msg} @ {baudrate} baud")
            else:
                raise RuntimeError(msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Connection Error", str(e))
            self._set_status(f"✗ Connection failed: {e}")

    def _disconnect(self):
        """Disconnect from serial port"""
        try:
            if self.worker:
                self._stop_polling()
            self.serial_mgr.disconnect_port()
            self._set_connected_ui(False)
            self._set_status("✓ Disconnected")
        except Exception as e:
            self._set_status(f"✗ Disconnect error: {e}")

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
            self._set_status(f"✓ Loaded {len(lines)} addresses from {fname}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load file:\n{e}")
            self._set_status(f"✗ Failed to load file: {e}")

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

            self.btnPolling.setText("⏸️ Stop Polling")
            self.btnPolling.setStyleSheet(f"QPushButton{{background:{Colors.ERROR}; color:{Colors.CR9}; font-weight:700; padding:10px; border:2px solid {Colors.CR5}; border-radius:6px;}} QPushButton:hover{{background:#dc2626; border-color:{Colors.CR6};}}")
            self._set_status("✓ Polling started")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            self._set_status(f"✗ Failed to start polling: {e}")

    def _stop_polling(self):
        """Stop auto-polling"""
        if self.worker:
            self.worker.stop()
            self.worker.wait(1500)
            self.worker = None
        self.btnPolling.setText("▶️ Start Polling")
        self.btnPolling.setStyleSheet(f"QPushButton{{background:{Colors.CR3}; color:{Colors.CR9}; font-weight:700; padding:10px; border:2px solid {Colors.CR5}; border-radius:6px;}} QPushButton:hover{{background:{Colors.CR4}; border-color:{Colors.CR6};}}")
        self._set_status("✓ Polling stopped")

    @QtCore.pyqtSlot(int, object, object)
    def _on_register_update(self, index: int, value: Optional[int], error: Optional[str]):
        """Update register display from polling thread"""
        if value is not None:
            self.rowValues[index].setText(str(value))
            self.rowValues[index].setStyleSheet(f"color:{Colors.CR9}; background:{Colors.CR2}; padding:8px; border:2px solid {Colors.CR5}; border-radius:4px; font-weight:600; font-size:14px;")
        else:
            text = "Timeout" if (error and "timeout" in error.lower()) else "ERR"
            self.rowValues[index].setText(text)
            self.rowValues[index].setStyleSheet(f"color:{Colors.ERROR}; background:{Colors.CR1}; padding:8px; border:2px solid {Colors.ERROR}; border-radius:4px; font-weight:600; font-size:14px;")

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
            self.rowValues[index].setStyleSheet(f"color:{Colors.CR9}; background:{Colors.CR2}; padding:8px; border:2px solid {Colors.CR5}; border-radius:4px; font-weight:600; font-size:14px;")
            self._set_status(f"✓ Write successful: Address {addr} = {shown}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Write Error", str(e))
            self._set_status(f"✗ Write failed: {e}")

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

    # Dark palette with custom theme - using all 9 colors
    app.setStyle("Fusion")
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(Colors.CR1))           # Darkest background
    palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(Colors.CR9))      # Lightest text
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(Colors.CR2))            # Input base color
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(Colors.CR3))   # Alternate rows
    palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(Colors.CR8))     # Tooltip background
    palette.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(Colors.CR1))     # Tooltip text
    palette.setColor(QtGui.QPalette.Text, QtGui.QColor(Colors.CR9))            # Primary text
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(Colors.CR3))          # Button background
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(Colors.CR9))      # Button text

    palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor(Colors.ERROR))    # Error text
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(Colors.CR4))       # Selection highlight
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(Colors.CR9)) # Selected text
    app.setPalette(palette)

    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
