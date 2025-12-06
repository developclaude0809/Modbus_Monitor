"""
View layer for Modbus Monitor V1
- UI construction using Panel components (Step 4: Panel-ization)
- All widgets exposed for MainWindow to connect signals
- Separates UI from business logic
"""

from PyQt5 import QtCore, QtGui, QtWidgets
from theme import Colors, UiTokens
from typing import List

# Import panel components (Step 4: Panel-ization)
from panels import (
    UARTPanel,
    MotorPanel,
    RWPanel,
    RDPanel,
    ResetPanel,
    PlotPanel,
)


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
    """Main view for V1 - builds UI using Panel components (Step 4: Panel-ization)"""

    def __init__(self, tokens, parent=None):
        super().__init__(parent)
        self.tokens = tokens

        # Panel instances (Step 4: Panel-ization)
        self.uart_panel: UARTPanel = None
        self.motor_panel: MotorPanel = None
        self.rw_panel: RWPanel = None
        self.rd_panel: RDPanel = None
        self.reset_panel: ResetPanel = None
        self.plot_panel: PlotPanel = None

        # UI widgets will be re-exported from panels for backward compatibility
        # UART panel widgets
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

        # RW panel widgets
        self.btnPolling = None
        self.edTimeout = None
        self.edPoll = None
        self.rowCombos: List = []
        self.rowReads: List = []
        self.rowWrites: List = []

        # Input register widgets
        self.inputRegLabels: List = []
        self.inputRegValues: List = []

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
        self.plotLabels: List = []
        self.plotCombos: List = []
        self.probeValueLabels: List = []
        self.btnModeSwitch = None
        self.cmbRRPage = None
        self.btnLoadDtbpt = None
        self.btnDraw = None
        self.plot_figure = None
        self.plot_canvas = None
        self.plot_ax = None
        self.plot_lines: List = []
        self.plot_toolbar = None

        # Status bar
        self.status = None

    def setup_ui(self, window: QtWidgets.QMainWindow):
        """Build the complete UI using Panel components and set it as the window's central widget

        This method is called by MainWindow to construct all UI elements.
        All widgets are re-exported from panels for MainWindow to access.
        """
        root = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(root)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Create panel instances (Step 4: Panel-ization)
        self.uart_panel = UARTPanel(self.tokens)
        self.motor_panel = MotorPanel(self.tokens)
        self.rw_panel = RWPanel(self.tokens)
        self.rd_panel = RDPanel(self.tokens)
        self.reset_panel = ResetPanel(self.tokens)
        self.plot_panel = PlotPanel(self.tokens)

        # Add UART panel to main layout
        main_layout.addWidget(self.uart_panel)

        # Create left column with Motor Control and Read Addresses panels
        left_column = QtWidgets.QVBoxLayout()
        left_column.setSpacing(8)
        left_column.addWidget(self.motor_panel)
        left_column.addWidget(self.rw_panel)

        # Create top row for RD and Reset panels (above plot panel)
        top_control_row = QtWidgets.QHBoxLayout()
        top_control_row.setSpacing(8)
        top_control_row.addWidget(self.rd_panel)
        top_control_row.addWidget(self.reset_panel)

        # Create right column with top control row and plot panel
        right_column = QtWidgets.QVBoxLayout()
        right_column.setSpacing(8)
        right_column.addLayout(top_control_row)
        right_column.addWidget(self.plot_panel)

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

        # Re-export widgets from panels for backward compatibility (Step 3 pattern)
        self._reexport_widgets()

    def _reexport_widgets(self):
        """Re-export widgets from panels for backward compatibility with existing code"""
        # UART panel widgets
        self.cmbPort = self.uart_panel.cmbPort
        self.cmbBaud = self.uart_panel.cmbBaud
        self.cmbDataBits = self.uart_panel.cmbDataBits
        self.cmbParity = self.uart_panel.cmbParity
        self.cmbStopBits = self.uart_panel.cmbStopBits
        self.edSlave = self.uart_panel.edSlave
        self.btnLoad = self.uart_panel.btnLoad
        self.btnRefreshPorts = self.uart_panel.btnRefreshPorts
        self.btnConnect = self.uart_panel.btnConnect

        # Motor panel widgets
        self.edMotorValue = self.motor_panel.edMotorValue
        self.btnMotorSend = self.motor_panel.btnMotorSend
        self.btnMotorStop = self.motor_panel.btnMotorStop
        self.btnFanInfo = self.motor_panel.btnFanInfo
        self.btnAlarmLog = self.motor_panel.btnAlarmLog

        # RW panel widgets
        self.btnPolling = self.rw_panel.btnPolling
        self.edTimeout = self.rw_panel.edTimeout
        self.edPoll = self.rw_panel.edPoll
        self.rowCombos = self.rw_panel.rowCombos
        self.rowReads = self.rw_panel.rowReads
        self.rowWrites = self.rw_panel.rowWrites
        self.inputRegLabels = self.rw_panel.inputRegLabels
        self.inputRegValues = self.rw_panel.inputRegValues

        # RD panel widgets
        self.lblNormalLight = self.rd_panel.lblNormalLight
        self.btnNormal = self.rd_panel.btnNormal
        self.rdCombo = self.rd_panel.rdCombo
        self.lblBypassLight = self.rd_panel.lblBypassLight
        self.btnBypass = self.rd_panel.btnBypass
        self.btnSwitch = self.rd_panel.btnSwitch

        # Reset panel widgets
        self.btnReset = self.reset_panel.btnReset
        self.btnResetDef = self.reset_panel.btnResetDef

        # Plot panel widgets
        self.plotLabels = self.plot_panel.plotLabels
        self.plotCombos = self.plot_panel.plotCombos
        self.probeValueLabels = self.plot_panel.probeValueLabels
        self.btnModeSwitch = self.plot_panel.btnModeSwitch
        self.cmbRRPage = self.plot_panel.cmbRRPage
        self.btnLoadDtbpt = self.plot_panel.btnLoadDtbpt
        self.btnDraw = self.plot_panel.btnDraw
        self.plot_figure = self.plot_panel.plot_figure
        self.plot_canvas = self.plot_panel.plot_canvas
        self.plot_ax = self.plot_panel.plot_ax
        self.plot_lines = self.plot_panel.plot_lines
        self.plot_toolbar = self.plot_panel.plot_toolbar
