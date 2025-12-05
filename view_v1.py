"""
View layer for Modbus Monitor V1
- UI construction only (no logic)
- All widgets exposed for MainWindow to connect signals
- Separates UI from business logic
"""

from PyQt5 import QtCore, QtGui, QtWidgets
from theme import Colors, UiTokens
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT
from typing import List


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


class MainView(QtCore.QObject):
    """Main view for V1 - builds UI but no logic"""

    def __init__(self, tokens: UiTokens, parent=None):
        super().__init__(parent)
        self.tokens = tokens

        # UI widgets will be created in setup_ui()
        # These will be accessed by MainWindow
        self.cmbPort = None
        self.cmbBaud = None
        self.cmbDataBits = None
        self.cmbParity = None
        self.cmbStopBits = None
        self.edSlave = None
        self.btnLoad = None
        self.btnRefreshPorts = None
        self.btnConnect = None

        # Motor panel widgets
        self.edMotorValue = None
        self.btnMotorSend = None
        self.btnMotorStop = None
        self.btnFanInfo = None
        self.btnAlarmLog = None

        # Polling panel widgets
        self.btnPolling = None
        self.edTimeout = None
        self.edPoll = None
        self.rowCombos = []
        self.rowReads = []
        self.rowWrites = []

        # RD panel widgets
        self.lblNormalLight = None
        self.btnNormal = None
        self.rdCombo = None
        self.lblBypassLight = None
        self.btnBypass = None
        self.btnSwitch = None

        # Reset panel widgets
        self.btnReset = None
        self.btnResetDef = None

        # Plot panel widgets
        self.plotLabels = []
        self.plotCombos = []
        self.probeValueLabels = []
        self.btnModeSwitch = None
        self.cmbRRPage = None
        self.btnLoadDtbpt = None
        self.btnDraw = None
        self.plot_figure = None
        self.plot_canvas = None
        self.plot_ax = None
        self.plot_lines = []
        self.plot_toolbar = None

        # Input register widgets
        self.inputRegLabels = []
        self.inputRegValues = []

        # Status bar
        self.status = None

    def setup_ui(self, window: QtWidgets.QMainWindow):
        """Build the complete UI and set it as the window's central widget

        This method is called by MainWindow to construct all UI elements.
        All widgets are stored as instance variables for MainWindow to access.
        """
        root = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(root)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Build UI panels
        uart_panel = self._build_uart_panel(window)
        motor_panel = self._build_motor_panel(window)
        rw_panel = self._build_rw_panel(window)
        rd_panel = self._build_rd_panel(window)
        reset_panel = self._build_reset_panel(window)
        plot_panel = self._build_plot_panel(window)

        # Add UART panel to main layout
        main_layout.addWidget(uart_panel)

        # Create left column with Motor Control and Read Addresses panels
        left_column = QtWidgets.QVBoxLayout()
        left_column.setSpacing(8)
        left_column.addWidget(motor_panel)
        left_column.addWidget(rw_panel)

        # Create top row for RD and Reset panels (above plot panel)
        top_control_row = QtWidgets.QHBoxLayout()
        top_control_row.setSpacing(8)
        top_control_row.addWidget(rd_panel)
        top_control_row.addWidget(reset_panel)

        # Create right column with top control row and plot panel
        right_column = QtWidgets.QVBoxLayout()
        right_column.setSpacing(8)
        right_column.addLayout(top_control_row)
        right_column.addWidget(plot_panel)

        # Add left and right columns to main layout
        content_row = QtWidgets.QHBoxLayout()
        content_row.setSpacing(8)
        content_row.addLayout(left_column)
        content_row.addLayout(right_column)
        main_layout.addLayout(content_row)

        # Status bar
        self.status = QtWidgets.QStatusBar()
        window.setStatusBar(self.status)

        window.setCentralWidget(root)

    def _build_uart_panel(self, window):
        """Build UART settings panel"""
        uart_panel = QtWidgets.QFrame()
        uart_panel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        uart_panel.setStyleSheet(
            f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} "
            f"QLabel{{color:{Colors.TEXT_LABEL};}}"
        )
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

        # Slave ID
        lblSlave = QtWidgets.QLabel("ID")
        lblSlave.setFixedWidth(80)
        lblSlave.setAlignment(QtCore.Qt.AlignCenter)
        lblSlave.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        uart_layout.addWidget(lblSlave)
        self.edSlave = QtWidgets.QLineEdit("1")
        self.edSlave.setValidator(QtGui.QIntValidator(1, 247, window))
        self.edSlave.setFixedWidth(70)
        self.edSlave.setStyleSheet(
            f"background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; "
            f"border:2px solid {Colors.BORDER_NORMAL}; padding:4px; border-radius:4px;"
        )
        uart_layout.addWidget(self.edSlave)

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
        self.btnLoad.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        uart_layout.addWidget(self.btnLoad)

        # Refresh button
        self.btnRefreshPorts = QtWidgets.QPushButton("Refresh")
        self.btnRefreshPorts.setToolTip("Refresh COM ports")
        self.btnRefreshPorts.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        uart_layout.addWidget(self.btnRefreshPorts)

        # Connect button
        self.btnConnect = QtWidgets.QPushButton("Connect")
        self.btnConnect.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; padding:8px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}"
        )
        uart_layout.addWidget(self.btnConnect)

        return uart_panel

    def _build_motor_panel(self, window):
        """Build motor control panel"""
        motor_panel = QtWidgets.QFrame()
        motor_panel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        motor_panel.setStyleSheet(
            f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} "
            f"QLabel{{color:{Colors.TEXT_LABEL};}}"
        )
        motor_panel.setMinimumSize(self.tokens.panel_minw(), 108)
        motor_panel.setMaximumHeight(108)
        motor_panel.setMaximumWidth(650)
        motor_panel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

        motor_main_layout = QtWidgets.QVBoxLayout(motor_panel)
        motor_main_layout.setContentsMargins(self.tokens.pad(), self.tokens.pad(), self.tokens.pad(), self.tokens.pad())
        motor_main_layout.setSpacing(8)

        # Top row: input box and buttons
        motor_top_layout = QtWidgets.QHBoxLayout()
        motor_top_layout.setSpacing(self.tokens.gap())

        # Value input for motor control
        self.edMotorValue = QtWidgets.QLineEdit()
        self.edMotorValue.setText("0")
        self.edMotorValue.setValidator(QtGui.QIntValidator(0, 65535, window))
        self.edMotorValue.setMinimumHeight(40)
        self.edMotorValue.setMaximumHeight(40)
        self.edMotorValue.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.edMotorValue.setStyleSheet(
            f"QLineEdit{{background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; "
            f"border:2px solid {Colors.BORDER_NORMAL}; padding:4px; border-radius:4px; font-size:{self.tokens.font_large()}px; font-weight:700;}} "
            f"QLineEdit:focus{{border-color:{Colors.BORDER_FOCUS};}}"
        )
        motor_top_layout.addWidget(self.edMotorValue)

        # Send button
        self.btnMotorSend = QtWidgets.QPushButton("Send")
        self.btnMotorSend.setMinimumSize(self.tokens.btn_w(), 40)
        self.btnMotorSend.setMaximumHeight(40)
        self.btnMotorSend.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.btnMotorSend.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:600; font-size:{self.tokens.font_xlarge()}px; padding:4px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}"
        )
        motor_top_layout.addWidget(self.btnMotorSend)

        # Stop button
        self.btnMotorStop = QtWidgets.QPushButton("Stop")
        self.btnMotorStop.setMinimumSize(self.tokens.btn_w(), 40)
        self.btnMotorStop.setMaximumHeight(40)
        self.btnMotorStop.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.btnMotorStop.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_DANGER_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:600; font-size:{self.tokens.font_xlarge()}px; padding:4px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.BTN_DANGER_BG};}}"
        )
        motor_top_layout.addWidget(self.btnMotorStop)

        motor_main_layout.addLayout(motor_top_layout)

        # Bottom row: Fan Info and Alarm Log buttons
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
        motor_bottom_layout.addWidget(self.btnFanInfo)

        # Alarm Log button
        self.btnAlarmLog = QtWidgets.QPushButton("Alarm Log")
        self.btnAlarmLog.setMinimumHeight(40)
        self.btnAlarmLog.setMaximumHeight(40)
        self.btnAlarmLog.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.btnAlarmLog.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; font-weight:600; font-size:{self.tokens.font_xlarge()}px; padding:4px 12px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        motor_bottom_layout.addWidget(self.btnAlarmLog)

        motor_main_layout.addLayout(motor_bottom_layout)

        return motor_panel

    def _build_rw_panel(self, window):
        """Build Read/Write Addresses panel with register grid and input registers"""
        # Import constants from logic or use defaults
        try:
            from logic import DEFAULT_TIMEOUT_MS, DEFAULT_POLL_INTERVAL_MS
        except ImportError:
            DEFAULT_TIMEOUT_MS = 500
            DEFAULT_POLL_INTERVAL_MS = 1000

        RWpanel = QtWidgets.QFrame()
        RWpanel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        RWpanel.setStyleSheet(
            f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} "
            f"QLabel{{color:{Colors.TEXT_LABEL};}}"
        )
        RWpanel.setMinimumSize(550, 750)
        RWpanel.setMaximumWidth(650)
        RWpanel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)

        rv = QtWidgets.QVBoxLayout(RWpanel)
        rv.setContentsMargins(3, 1, 3, 1)
        rv.setSpacing(8)

        # Top row: Start button
        topRow = QtWidgets.QWidget()
        topLayout = QtWidgets.QHBoxLayout(topRow)
        topLayout.setSpacing(0)
        topLayout.setContentsMargins(6, 0, 6, 0)

        # Start/Stop Polling button
        self.btnPolling = QtWidgets.QPushButton("Start")
        self.btnPolling.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}"
        )
        topLayout.addWidget(self.btnPolling)

        # Timeout and Poll interval inputs
        self.edTimeout = QtWidgets.QLineEdit(str(DEFAULT_TIMEOUT_MS))
        self.edPoll = QtWidgets.QLineEdit(str(DEFAULT_POLL_INTERVAL_MS))

        topLayout.addStretch()
        rv.addWidget(topRow)

        # Register grid (10 rows)
        gridWidget = QtWidgets.QWidget()
        gridWidget.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        grid = QtWidgets.QGridLayout(gridWidget)
        grid.setContentsMargins(1, 5, 1, 5)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(7)
        grid.setColumnStretch(0, 8)
        grid.setColumnStretch(1, 6)
        grid.setColumnStretch(2, 6)

        self.rowCombos: List[SearchableCombo] = []
        self.rowReads: List[QtWidgets.QLabel] = []
        self.rowWrites: List[QtWidgets.QLineEdit] = []

        for i in range(10):
            # Address selector combo
            combo = SearchableCombo(half_width=False)
            combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            combo.setMinimumHeight(25)
            combo.addItem("---")
            grid.addWidget(combo, i, 0)
            self.rowCombos.append(combo)

            # Read value display
            val = QtWidgets.QLabel("----")
            val.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            val.setMinimumHeight(25)
            val.setStyleSheet(
                f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; "
                f"padding:6px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; "
                f"font-weight:600; font-size:14px;"
            )
            grid.addWidget(val, i, 1)
            self.rowReads.append(val)

            # Write value input
            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText("Enter value (0-65535)")
            edit.setValidator(QtGui.QIntValidator(0, 65535, window))
            edit.setMinimumHeight(25)
            edit.setStyleSheet(
                f"QLineEdit{{background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; "
                f"border:2px solid {Colors.BORDER_NORMAL}; padding:4px; border-radius:4px;}} "
                f"QLineEdit:focus{{border-color:{Colors.BORDER_FOCUS};}}"
            )
            edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            grid.addWidget(edit, i, 2)
            self.rowWrites.append(edit)

        rv.addWidget(gridWidget)

        # Input Register Display (FC 0x04)
        inputRegFrame = QtWidgets.QFrame()
        inputRegFrame.setMinimumHeight(250)
        inputRegFrame.setMaximumHeight(400)
        inputRegFrame.setStyleSheet(
            f"QFrame{{background:{Colors.BG_PANEL}; border:2px solid {Colors.BORDER_PANEL}; border-radius:6px;}}"
        )

        inputGrid = QtWidgets.QGridLayout(inputRegFrame)
        inputGrid.setContentsMargins(3, 3, 3, 3)
        inputGrid.setHorizontalSpacing(8)
        inputGrid.setVerticalSpacing(2)

        # Add 12 input registers (IN0-IN11)
        self.inputRegLabels: List[QtWidgets.QLabel] = []
        self.inputRegValues: List[QtWidgets.QLabel] = []

        for i in range(8):
            row = i // 2
            col = i % 2

            container = QtWidgets.QWidget()
            hbox = QtWidgets.QHBoxLayout(container)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.setSpacing(8)

            lbl = QtWidgets.QLabel(f"IN{i}")
            lbl.setFixedWidth(130)
            lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            lbl.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700; font-size:14px; padding:4px;")
            hbox.addWidget(lbl)
            self.inputRegLabels.append(lbl)

            val = QtWidgets.QLabel("----")
            val.setAlignment(QtCore.Qt.AlignCenter)
            val.setStyleSheet(
                f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; "
                f"padding:8px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; "
                f"font-weight:600; font-size:16px;"
            )
            hbox.addWidget(val)
            self.inputRegValues.append(val)

            inputGrid.addWidget(container, row, col)

        # Add IN8-IN11
        for i in range(8, 12):
            row = 4 + (i - 8) // 2
            col = (i - 8) % 2

            container = QtWidgets.QWidget()
            hbox = QtWidgets.QHBoxLayout(container)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.setSpacing(8)

            lbl = QtWidgets.QLabel(f"IN{i}")
            lbl.setFixedWidth(130)
            lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            lbl.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700; font-size:14px; padding:4px;")
            hbox.addWidget(lbl)
            self.inputRegLabels.append(lbl)

            val = QtWidgets.QLabel("----")
            val.setAlignment(QtCore.Qt.AlignCenter)
            val.setStyleSheet(
                f"color:{Colors.VALUE_DISPLAY_TEXT}; background:{Colors.VALUE_DISPLAY_BG}; "
                f"padding:8px; border:2px solid {Colors.BORDER_NORMAL}; border-radius:4px; "
                f"font-weight:600; font-size:16px;"
            )
            hbox.addWidget(val)
            self.inputRegValues.append(val)

            inputGrid.addWidget(container, row, col)

        rv.addWidget(inputRegFrame)

        return RWpanel

    def _build_rd_panel(self, window):
        """Build RD Panel (Special Command Buttons)"""
        RDpanel = QtWidgets.QFrame()
        RDpanel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        RDpanel.setStyleSheet(
            f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} "
            f"QLabel{{color:{Colors.TEXT_LABEL};}}"
        )
        RDpanel.setMinimumHeight(self.tokens.panel_h_control())
        RDpanel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)

        rd_layout = QtWidgets.QGridLayout(RDpanel)
        rd_layout.setContentsMargins(int(10 * self.tokens.s), self.tokens.pad()//2, int(50 * self.tokens.s), self.tokens.pad()//2)
        rd_layout.setHorizontalSpacing(int(15 * self.tokens.s))
        rd_layout.setVerticalSpacing(int(8 * self.tokens.s))

        # Row 0, Col 0: Normal indicator
        self.lblNormalLight = QtWidgets.QLabel("Normal")
        self.lblNormalLight.setAlignment(QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter)
        self.lblNormalLight.setStyleSheet(
            f"QLabel{{color:{Colors.BG_INPUT}; font-weight:700; font-size:{self.tokens.font_large()}px; padding:0px; border:none;}}"
        )
        rd_layout.addWidget(self.lblNormalLight, 0, 0)

        # Row 0, Col 1: Normal button
        self.btnNormal = QtWidgets.QPushButton("Normal")
        self.btnNormal.setMinimumWidth(self.tokens.btn_w())
        self.btnNormal.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        self.btnNormal.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:{self.tokens.font_medium()}px; padding:3px 3px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        rd_layout.addWidget(self.btnNormal, 0, 1)

        # Row 0, Col 2: List combobox
        self.rdCombo = SearchableCombo(half_width=False)
        self.rdCombo.addItems(["Inverter", "Converter", "Gsensor"])
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
        self.rdCombo.setMinimumWidth(self.tokens.combo_w())
        self.rdCombo.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        rd_layout.addWidget(self.rdCombo, 0, 2)

        # Row 1, Col 0: Bypass indicator
        self.lblBypassLight = QtWidgets.QLabel("Bypass")
        self.lblBypassLight.setAlignment(QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter)
        self.lblBypassLight.setStyleSheet(
            f"QLabel{{color:{Colors.BG_INPUT}; font-weight:700; font-size:{self.tokens.font_large()}px; padding:0px; border:none;}}"
        )
        rd_layout.addWidget(self.lblBypassLight, 1, 0)

        # Row 1, Col 1: Bypass button
        self.btnBypass = QtWidgets.QPushButton("Bypass")
        self.btnBypass.setMinimumWidth(self.tokens.btn_w())
        self.btnBypass.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        self.btnBypass.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:{self.tokens.font_medium()}px; padding:5px 5px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        rd_layout.addWidget(self.btnBypass, 1, 1)

        # Row 1, Col 2: Switch button
        self.btnSwitch = QtWidgets.QPushButton("Switch")
        self.btnSwitch.setMinimumWidth(self.tokens.btn_w())
        self.btnSwitch.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        self.btnSwitch.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:{self.tokens.font_medium()}px; padding:5px 5px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        rd_layout.addWidget(self.btnSwitch, 1, 2)

        return RDpanel

    def _build_reset_panel(self, window):
        """Build Reset Panel with Reset and Reset Def buttons"""
        ResetPanel = QtWidgets.QFrame()
        ResetPanel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        ResetPanel.setStyleSheet(
            f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} "
            f"QLabel{{color:{Colors.TEXT_LABEL};}}"
        )
        ResetPanel.setMinimumSize(int(200 * self.tokens.s), int(80 * self.tokens.s))
        ResetPanel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)

        reset_layout = QtWidgets.QVBoxLayout(ResetPanel)
        reset_layout.setContentsMargins(self.tokens.pad(), self.tokens.pad(), self.tokens.pad(), self.tokens.pad())
        reset_layout.setSpacing(self.tokens.gap())

        # Reset button
        self.btnReset = QtWidgets.QPushButton("Reset")
        self.btnReset.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.btnReset.setMinimumHeight(int(20 * self.tokens.s))
        self.btnReset.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:{self.tokens.font_normal()}px; padding:1px 10px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        reset_layout.addWidget(self.btnReset)

        # Reset Def button
        self.btnResetDef = QtWidgets.QPushButton("Reset Def")
        self.btnResetDef.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.btnResetDef.setMinimumHeight(int(20 * self.tokens.s))
        self.btnResetDef.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:600; font-size:{self.tokens.font_normal()}px; padding:1px 10px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        reset_layout.addWidget(self.btnResetDef)

        return ResetPanel

    def _build_plot_panel(self, window):
        """Build Plot Panel with matplotlib canvas and controls"""
        plot_panel = QtWidgets.QFrame()
        plot_panel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        plot_panel.setStyleSheet(
            f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} "
            f"QLabel{{color:{Colors.TEXT_LABEL};}}"
        )
        plot_panel.setMinimumHeight(600)
        plot_panel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        pv = QtWidgets.QVBoxLayout(plot_panel)
        pv.setContentsMargins(2, 2, 2, 2)
        pv.setSpacing(1)

        # Address selection: 4 SearchableCombo boxes
        addrWidget = QtWidgets.QWidget()
        addrLayout = QtWidgets.QGridLayout(addrWidget)
        addrLayout.setContentsMargins(0, 0, 0, 0)
        addrLayout.setHorizontalSpacing(4)
        addrLayout.setVerticalSpacing(1)

        self.plotCombos: List[SearchableCombo] = []
        self.plotLabels: List[ClickableLabel] = []
        self.probeValueLabels: List[QtWidgets.QLabel] = []
        channel_colors = [Colors.BENIUKON, Colors.MINT_GLOW, Colors.SOFT_YELLOW, Colors.ROSE_CORAL]

        for i in range(4):
            lbl = ClickableLabel(f"Ch{i+1}")
            lbl.setStyleSheet(
                f"color:{channel_colors[i]}; font-weight:700; border:2px solid {channel_colors[i]}; "
                f"border-radius:4px; padding:4px;"
            )
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            lbl.setFixedWidth(40)
            self.plotLabels.append(lbl)

            combo = SearchableCombo(half_width=False)
            combo.addItem("---")
            combo.setStyleSheet(f"font-size:12px; font-weight:500; border:2px solid {channel_colors[i]};")
            combo.setFixedHeight(35)

            row = 0
            col = i * 2
            addrLayout.addWidget(lbl, row, col)
            addrLayout.addWidget(combo, row, col + 1)
            self.plotCombos.append(combo)

            # Probe value label
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

        # RR Mode controls row
        rr_control_widget = QtWidgets.QWidget()
        rr_control_layout = QtWidgets.QHBoxLayout(rr_control_widget)
        rr_control_layout.setContentsMargins(0, 5, 0, 5)
        rr_control_layout.setSpacing(10)

        # Mode switch button
        self.btnModeSwitch = QtWidgets.QPushButton("03")
        self.btnModeSwitch.setStyleSheet(
            f"QPushButton{{background:{Colors.MIDNIGHT_OCEAN}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:700; font-size:16px; padding:8px 20px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.MIDNIGHT_OCEAN};}}"
        )
        self.btnModeSwitch.setFixedHeight(35)
        self.btnModeSwitch.setFixedWidth(80)
        rr_control_layout.addWidget(self.btnModeSwitch)

        # RR Mode page selector
        lbl_page = QtWidgets.QLabel("Page:")
        lbl_page.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:600; font-size:14px;")
        rr_control_layout.addWidget(lbl_page)

        self.cmbRRPage = SearchableCombo(half_width=False)
        self.cmbRRPage.setMinimumWidth(80)
        self.cmbRRPage.setFixedHeight(35)
        for i in range(13):
            self.cmbRRPage.addItem(str(i))
        self.cmbRRPage.setCurrentText("0")
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
        rr_control_layout.addWidget(self.btnLoadDtbpt)

        # Initially disable RR controls
        self.cmbRRPage.setEnabled(False)
        self.btnLoadDtbpt.setEnabled(False)

        rr_control_layout.addStretch()
        pv.addWidget(rr_control_widget)

        # Draw button
        self.btnDraw = QtWidgets.QPushButton("Draw")
        self.btnDraw.setStyleSheet(
            f"QPushButton{{background:{Colors.BTN_SUCCESS_BG}; color:{Colors.BTN_TEXT_COLOR}; "
            f"font-weight:700; font-size:16px; padding:10px; border:none; border-radius:6px;}} "
            f"QPushButton:hover{{background:{Colors.AKAKUCHIBA};}} "
            f"QPushButton:pressed{{background:{Colors.BTN_SUCCESS_BG};}}"
        )
        self.btnDraw.setFixedHeight(40)
        self.btnDraw.setFixedWidth(250)
        pv.addWidget(self.btnDraw, alignment=QtCore.Qt.AlignHCenter)

        # Matplotlib canvas
        self.plot_figure = Figure(figsize=(8, 6), dpi=100, facecolor=Colors.BG_PANEL)
        self.plot_canvas = FigureCanvas(self.plot_figure)
        self.plot_canvas.setStyleSheet(f"background:{Colors.BG_PANEL};")
        self.plot_ax = self.plot_figure.add_subplot(111, facecolor=Colors.COOL_GRAY)
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
            line.set_antialiased(False)
            self.plot_lines.append(line)
        self.plot_ax.legend(loc='upper left', facecolor=Colors.BG_PANEL, edgecolor=Colors.BORDER_NORMAL, labelcolor=Colors.TEXT_PRIMARY)

        # Navigation toolbar
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

        return plot_panel
