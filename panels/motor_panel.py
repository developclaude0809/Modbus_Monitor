"""
Motor Control Panel
- Motor value input
- Send/Stop buttons
- Fan Info and Alarm Log buttons
"""

from PyQt5 import QtCore, QtGui, QtWidgets
from theme import Colors


class MotorPanel(QtWidgets.QFrame):
    """Motor Control Panel with signals for button clicks"""

    # Signals for controller to connect
    sig_send_clicked = QtCore.pyqtSignal()
    sig_stop_clicked = QtCore.pyqtSignal()
    sig_fan_info_clicked = QtCore.pyqtSignal()
    sig_alarm_log_clicked = QtCore.pyqtSignal()

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
        self.setMinimumSize(self.tokens.panel_minw(), 108)
        self.setMaximumHeight(108)
        self.setMaximumWidth(650)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(self.tokens.pad(), self.tokens.pad(), self.tokens.pad(), self.tokens.pad())
        main_layout.setSpacing(8)

        # Top row: input box and buttons
        top_layout = QtWidgets.QHBoxLayout()
        top_layout.setSpacing(self.tokens.gap())

        # Value input for motor control
        self.edMotorValue = QtWidgets.QLineEdit()
        self.edMotorValue.setText("0")
        self.edMotorValue.setValidator(QtGui.QIntValidator(0, 65535))
        self.edMotorValue.setMinimumHeight(40)
        self.edMotorValue.setMaximumHeight(40)
        self.edMotorValue.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.edMotorValue.setStyleSheet(
            f"QLineEdit{{background:{Colors.BG_INPUT}; color:{Colors.TEXT_PRIMARY}; "
            f"border:2px solid {Colors.BORDER_NORMAL}; padding:4px; border-radius:4px; font-size:{self.tokens.font_large()}px; font-weight:700;}} "
            f"QLineEdit:focus{{border-color:{Colors.BORDER_FOCUS};}}"
        )
        top_layout.addWidget(self.edMotorValue)

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
        self.btnMotorSend.clicked.connect(self.sig_send_clicked.emit)
        top_layout.addWidget(self.btnMotorSend)

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
        self.btnMotorStop.clicked.connect(self.sig_stop_clicked.emit)
        top_layout.addWidget(self.btnMotorStop)

        main_layout.addLayout(top_layout)

        # Bottom row: Fan Info and Alarm Log buttons
        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.setSpacing(self.tokens.gap())

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
        self.btnFanInfo.clicked.connect(self.sig_fan_info_clicked.emit)
        bottom_layout.addWidget(self.btnFanInfo)

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
        self.btnAlarmLog.clicked.connect(self.sig_alarm_log_clicked.emit)
        bottom_layout.addWidget(self.btnAlarmLog)

        main_layout.addLayout(bottom_layout)
