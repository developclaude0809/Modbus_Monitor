"""
RD Panel (Special Command Buttons)
- Normal/Bypass mode indicators
- Normal, Bypass, Switch buttons
- Mode selector combo
"""

from PyQt5 import QtCore, QtGui, QtWidgets
from theme import Colors


class SearchableCombo(QtWidgets.QComboBox):
    """Searchable combo box for RD panel"""

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


class RDPanel(QtWidgets.QFrame):
    """RD Panel (Special Commands) with signals"""

    # Signals for controller to connect
    sig_normal_clicked = QtCore.pyqtSignal()
    sig_bypass_clicked = QtCore.pyqtSignal()
    sig_switch_clicked = QtCore.pyqtSignal()
    sig_mode_changed = QtCore.pyqtSignal(str)  # Emits mode name when combo changes

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
        self.setMinimumHeight(self.tokens.panel_h_control())
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)

        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(int(10 * self.tokens.s), self.tokens.pad() // 2, int(50 * self.tokens.s), self.tokens.pad() // 2)
        layout.setHorizontalSpacing(int(15 * self.tokens.s))
        layout.setVerticalSpacing(int(8 * self.tokens.s))

        # Row 0, Col 0: Normal indicator
        self.lblNormalLight = QtWidgets.QLabel("Normal")
        self.lblNormalLight.setAlignment(QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter)
        self.lblNormalLight.setStyleSheet(
            f"QLabel{{color:{Colors.BG_INPUT}; font-weight:700; font-size:{self.tokens.font_large()}px; padding:0px; border:none;}}"
        )
        layout.addWidget(self.lblNormalLight, 0, 0)

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
        self.btnNormal.clicked.connect(self.sig_normal_clicked.emit)
        layout.addWidget(self.btnNormal, 0, 1)

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
        self.rdCombo.currentTextChanged.connect(self.sig_mode_changed.emit)
        layout.addWidget(self.rdCombo, 0, 2)

        # Row 1, Col 0: Bypass indicator
        self.lblBypassLight = QtWidgets.QLabel("Bypass")
        self.lblBypassLight.setAlignment(QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter)
        self.lblBypassLight.setStyleSheet(
            f"QLabel{{color:{Colors.BG_INPUT}; font-weight:700; font-size:{self.tokens.font_large()}px; padding:0px; border:none;}}"
        )
        layout.addWidget(self.lblBypassLight, 1, 0)

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
        self.btnBypass.clicked.connect(self.sig_bypass_clicked.emit)
        layout.addWidget(self.btnBypass, 1, 1)

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
        self.btnSwitch.clicked.connect(self.sig_switch_clicked.emit)
        layout.addWidget(self.btnSwitch, 1, 2)
