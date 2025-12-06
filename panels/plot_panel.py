"""
Plot Panel
- 4 channel selection combos with clickable labels
- Mode switch button (03/RR)
- RR Page selector
- Load .dtbpt button
- Draw button
- Matplotlib canvas with toolbar
"""

from typing import List
from PyQt5 import QtCore, QtGui, QtWidgets
from theme import Colors

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT


class SearchableCombo(QtWidgets.QComboBox):
    """Searchable combo box for Plot panel"""

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


class ClickableLabel(QtWidgets.QLabel):
    """QLabel that emits a clicked signal when pressed"""
    clicked = QtCore.pyqtSignal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class PlotPanel(QtWidgets.QFrame):
    """Plot Panel with signals for button clicks"""

    # Signals for controller to connect
    sig_mode_switch_clicked = QtCore.pyqtSignal()
    sig_load_dtbpt_clicked = QtCore.pyqtSignal()
    sig_draw_clicked = QtCore.pyqtSignal()
    sig_channel_label_clicked = QtCore.pyqtSignal(int)  # Channel index 0-3

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
        self.setMinimumHeight(600)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        pv = QtWidgets.QVBoxLayout(self)
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
            # Connect to signal with channel index
            lbl.clicked.connect(lambda checked, idx=i: self.sig_channel_label_clicked.emit(idx))
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
        self.btnModeSwitch.clicked.connect(self.sig_mode_switch_clicked.emit)
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
        self.btnLoadDtbpt.clicked.connect(self.sig_load_dtbpt_clicked.emit)
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
        self.btnDraw.clicked.connect(self.sig_draw_clicked.emit)
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
        self.plot_toolbar = NavigationToolbar2QT(self.plot_canvas, self)
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
