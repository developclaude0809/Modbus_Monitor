"""
View layer for Modbus Monitor V2
- Simplified UI excluding Plot and RR functions
- UI construction using Panel components
- All widgets exposed for MainWindow to connect signals
- Separates UI from business logic
"""

from PyQt5 import QtCore, QtGui, QtWidgets
from theme import Colors, UiTokens
from typing import List

# Import panel components (excluding PlotPanel)
from panels import (
    UARTPanel,
    MotorPanel,
    RWPanel,
    RDPanel,
    ResetPanel,
)


class MainView(QtCore.QObject):
    """Main view for V2 - simplified layout without Plot and RR functions"""

    def __init__(self, tokens, parent=None):
        super().__init__(parent)
        self.tokens = tokens

        # Panel instances
        self.uart_panel: UARTPanel = None
        self.motor_panel: MotorPanel = None
        self.rw_panel: RWPanel = None
        self.rd_panel: RDPanel = None
        self.reset_panel: ResetPanel = None

        # UI widgets re-exported from panels
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

        # Status bar
        self.status = None

    def setup_ui(self, window: QtWidgets.QMainWindow):
        """Build the simplified UI using Panel components (V2 - no Plot/RR)

        Layout structure:
        ┌──────────────────────────────────────┐
        │         UART Panel (top)             │
        ├────────────────┬─────────────────────┤
        │  Motor Panel   │   RD Panel          │
        │                ├─────────────────────┤
        │                │   Reset Panel       │
        ├────────────────┴─────────────────────┤
        │         RW Panel (bottom)            │
        └──────────────────────────────────────┘
        """
        root = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(root)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Create panel instances
        self.uart_panel = UARTPanel(self.tokens)
        self.motor_panel = MotorPanel(self.tokens)
        self.rw_panel = RWPanel(self.tokens)
        self.rd_panel = RDPanel(self.tokens)
        self.reset_panel = ResetPanel(self.tokens)

        # Add UART panel at top
        main_layout.addWidget(self.uart_panel)

        # Middle row: Motor panel on left, RD+Reset panels on right
        middle_row = QtWidgets.QHBoxLayout()
        middle_row.setSpacing(8)

        # Left side: Motor panel
        middle_row.addWidget(self.motor_panel)

        # Right side: RD and Reset panels stacked vertically
        right_column = QtWidgets.QVBoxLayout()
        right_column.setSpacing(8)
        right_column.addWidget(self.rd_panel)
        right_column.addWidget(self.reset_panel)

        middle_row.addLayout(right_column)
        main_layout.addLayout(middle_row)

        # Add RW panel at bottom
        main_layout.addWidget(self.rw_panel)

        # Status bar
        self.status = QtWidgets.QStatusBar()
        window.setStatusBar(self.status)

        window.setCentralWidget(root)

        # Re-export widgets from panels for backward compatibility
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
