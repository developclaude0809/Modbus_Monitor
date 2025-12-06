"""
Read/Write Addresses Panel
- Polling control (Start/Stop)
- Register grid (10 rows with address selector, read value, write input)
- Input register display (IN0-IN11)
"""

from typing import List
from PyQt5 import QtCore, QtGui, QtWidgets
from theme import Colors

# Default timing values
DEFAULT_TIMEOUT_MS = 500
DEFAULT_POLL_INTERVAL_MS = 1000


class SearchableCombo(QtWidgets.QComboBox):
    """Searchable combo box for RW panel"""

    def __init__(self, parent=None, half_width=True):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setCompleter(None)

        self._model = QtGui.QStandardItemModel(self)
        super().setModel(self._model)
        self.setModelColumn(0)

        self._allow_commit = False
        self._popup_open = False
        self._hovered = False

        self.installEventFilter(self)
        self.lineEdit().installEventFilter(self)
        self.view().installEventFilter(self)
        self.setMouseTracking(True)

        self.view().clicked.connect(self._on_view_activate)
        self.view().pressed.connect(self._on_view_activate)

        try:
            self.lineEdit().setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        except Exception:
            pass

        QtCore.QTimer.singleShot(0, self._reset_cursor_to_start)

        if half_width:
            self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
            self.setMaximumWidth(150)

        try:
            self.setStyleSheet(f"""
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
            """)
        except (NameError, AttributeError):
            pass

    def showPopup(self):
        super().showPopup()
        self._popup_open = True
        QtCore.QTimer.singleShot(0, self._highlight_first_match)

    def hidePopup(self):
        self._popup_open = False
        super().hidePopup()
        QtCore.QTimer.singleShot(0, self._reset_cursor_to_start)

    def _highlight_first_match(self):
        text = self.lineEdit().text().casefold()
        target_row = None
        if text:
            for row in range(self._model.rowCount()):
                val = self._model.item(row).text()
                if text in val.casefold():
                    target_row = row
                    break
        if target_row is None:
            target_row = max(0, self.currentIndex())
        idx = self.model().index(target_row, 0)
        self.view().setCurrentIndex(idx)
        self.view().selectionModel().setCurrentIndex(idx, QtCore.QItemSelectionModel.ClearAndSelect)
        self.view().scrollTo(idx, QtWidgets.QAbstractItemView.PositionAtCenter)

    def _commit_row(self, row: int):
        self._allow_commit = True
        try:
            super().setCurrentIndex(row)
        finally:
            self._allow_commit = False
        QtCore.QTimer.singleShot(0, self._reset_cursor_to_start)

    def _on_view_activate(self, mi: QtCore.QModelIndex):
        if not mi.isValid():
            return
        self._commit_row(mi.row())
        self.hidePopup()

    def setCurrentIndex(self, index: int):
        if self._allow_commit or index == -1:
            return super().setCurrentIndex(index)

    def eventFilter(self, obj, ev):
        if obj is self and ev.type() == QtCore.QEvent.ShortcutOverride:
            if ev.text() and not (ev.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)):
                ev.accept()
                return True
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
        if obj is self.view() and ev.type() == QtCore.QEvent.KeyPress:
            if ev.key() in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down,
                           QtCore.Qt.Key_PageUp, QtCore.Qt.Key_PageDown,
                           QtCore.Qt.Key_Home, QtCore.Qt.Key_End):
                QtWidgets.QAbstractItemView.keyPressEvent(self.view(), ev)
                return True
        return super().eventFilter(obj, ev)

    def enterEvent(self, event):
        self._hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        super().leaveEvent(event)

    def wheelEvent(self, event):
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
                self._commit_row(new_idx)
        else:
            event.ignore()

    def _reset_cursor_to_start(self):
        try:
            le = self.lineEdit()
            if le is not None:
                le.setCursorPosition(0)
        except Exception:
            pass

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        QtCore.QTimer.singleShot(0, self._reset_cursor_to_start)

    def addItem(self, text, userData=None):
        item = QtGui.QStandardItem(str(text))
        item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        if userData is not None:
            item.setData(userData, QtCore.Qt.UserRole)
        self._model.appendRow(item)

    def addItems(self, texts):
        for text in texts:
            self.addItem(text)

    def clear(self):
        self._model.clear()

    def count(self):
        return self._model.rowCount()

    def currentData(self, role=QtCore.Qt.UserRole):
        idx = self.currentIndex()
        if idx < 0 or idx >= self._model.rowCount():
            return None
        item = self._model.item(idx)
        return item.data(role) if item else None

    def itemData(self, index, role=QtCore.Qt.UserRole):
        if index < 0 or index >= self._model.rowCount():
            return None
        item = self._model.item(index)
        return item.data(role) if item else None

    def setModel(self, model):
        if model != self._model:
            self._model = model
            super().setModel(self._model)


class RWPanel(QtWidgets.QFrame):
    """Read/Write Addresses Panel with signals"""

    # Signals for controller to connect
    sig_polling_clicked = QtCore.pyqtSignal()

    def __init__(self, tokens, parent=None):
        super().__init__(parent)
        self.tokens = tokens
        self._build_ui()

    def _build_ui(self):
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setStyleSheet(
            f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} "
            f"QLabel{{color:{Colors.TEXT_LABEL};}}"
        )
        self.setMinimumSize(550, 750)
        self.setMaximumWidth(650)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)

        rv = QtWidgets.QVBoxLayout(self)
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
        self.btnPolling.clicked.connect(self.sig_polling_clicked.emit)
        topLayout.addWidget(self.btnPolling)

        # Timeout and Poll interval inputs (hidden, used internally)
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
            edit.setValidator(QtGui.QIntValidator(0, 65535))
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
