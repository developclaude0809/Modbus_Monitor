"""
View layer for Modbus Monitor V1
- UI construction only (no logic)
- All widgets exposed for MainWindow to connect signals
- Separates UI from business logic
"""

from PyQt5 import QtCore, QtGui, QtWidgets
from theme import Colors, UiTokens


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

        # Additional UI elements will be added as we extract them

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

        # Add panels to main layout
        main_layout.addWidget(uart_panel)
        main_layout.addWidget(motor_panel)

        # TODO: Add remaining panels (Read/Write, Plot, Input Registers, etc.)
        # For now, we'll start with the basic panels

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
