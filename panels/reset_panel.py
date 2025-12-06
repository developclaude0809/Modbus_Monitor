"""
Reset Panel
- Reset button
- Reset Def button
"""

from PyQt5 import QtCore, QtWidgets
from theme import Colors


class ResetPanel(QtWidgets.QFrame):
    """Reset Panel with signals for button clicks"""

    # Signals for controller to connect
    sig_reset_clicked = QtCore.pyqtSignal()
    sig_reset_def_clicked = QtCore.pyqtSignal()

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
        self.setMinimumSize(int(200 * self.tokens.s), int(80 * self.tokens.s))
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(self.tokens.pad(), self.tokens.pad(), self.tokens.pad(), self.tokens.pad())
        layout.setSpacing(self.tokens.gap())

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
        self.btnReset.clicked.connect(self.sig_reset_clicked.emit)
        layout.addWidget(self.btnReset)

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
        self.btnResetDef.clicked.connect(self.sig_reset_def_clicked.emit)
        layout.addWidget(self.btnResetDef)
