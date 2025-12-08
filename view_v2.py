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
        ┌──────────────┬─────────────────┐
        │ UART Panel   │  Motor Panel    │
        │ (vertical)   ├─────────────────┤
        ├──────────────┤  Reset Panel    │
        │ RD Panel     ├─────────────────┤
        │              │  RW Panel       │
        │              │  (right side)   │
        └──────────────┴─────────────────┘
        """
        root = QtWidgets.QWidget()
        main_layout = QtWidgets.QHBoxLayout(root)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Create panel instances
        self.uart_panel = UARTPanel(self.tokens)
        self.motor_panel = MotorPanel(self.tokens)
        self.rw_panel = RWPanel(self.tokens)
        self.rd_panel = RDPanel(self.tokens)
        self.reset_panel = ResetPanel(self.tokens)

        # Left side: Motor Panel (top) + Reset Panel (middle) + RW Panel (below)
        left_column = QtWidgets.QVBoxLayout()
        left_column.setSpacing(8)
        left_column.addWidget(self.motor_panel)

        # Constrain reset panel width to match motor panel
        self.reset_panel.setMaximumWidth(650)
        self.reset_panel.setMaximumHeight(108)
        self.reset_panel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        left_column.addWidget(self.reset_panel)

        left_column.addWidget(self.rw_panel)

        # Right side: UART + RD panels stacked vertically
        right_column = QtWidgets.QVBoxLayout()
        right_column.setSpacing(8)

        # Create vertical UART panel wrapper
        uart_vertical = self._create_vertical_uart_panel()
        right_column.addWidget(uart_vertical)

        # Create vertical RD panel wrapper
        rd_vertical = self._create_vertical_rd_panel()
        right_column.addWidget(rd_vertical)

        right_column.addStretch()

        # Add right column first (UART + RD on left), then left column (Motor + Reset + RW on right)
        main_layout.addLayout(right_column)
        main_layout.addLayout(left_column)

        # Status bar
        self.status = QtWidgets.QStatusBar()
        window.setStatusBar(self.status)

        window.setCentralWidget(root)

        # Re-export widgets from panels for backward compatibility
        self._reexport_widgets()

    def _create_vertical_uart_panel(self):
        """Create a vertical layout wrapper for UART panel widgets"""
        from theme import Colors

        # Create a frame to hold the vertical UART layout
        frame = QtWidgets.QFrame()
        frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        frame.setStyleSheet(
            f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} "
            f"QLabel{{color:{Colors.TEXT_LABEL};}}"
        )
        frame.setMinimumWidth(220)
        frame.setMaximumWidth(260)

        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Access UART panel widgets directly
        # Port row
        port_row = QtWidgets.QHBoxLayout()
        lbl_port = QtWidgets.QLabel("COM Port")
        lbl_port.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        lbl_port.setFixedWidth(80)
        port_row.addWidget(lbl_port)
        port_row.addWidget(self.uart_panel.cmbPort)
        layout.addLayout(port_row)

        # Baud row
        baud_row = QtWidgets.QHBoxLayout()
        lbl_baud = QtWidgets.QLabel("Baud")
        lbl_baud.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        lbl_baud.setFixedWidth(80)
        baud_row.addWidget(lbl_baud)
        baud_row.addWidget(self.uart_panel.cmbBaud)
        layout.addLayout(baud_row)

        # Data bits row
        databits_row = QtWidgets.QHBoxLayout()
        lbl_databits = QtWidgets.QLabel("Data Bits")
        lbl_databits.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        lbl_databits.setFixedWidth(80)
        databits_row.addWidget(lbl_databits)
        databits_row.addWidget(self.uart_panel.cmbDataBits)
        layout.addLayout(databits_row)

        # Parity row
        parity_row = QtWidgets.QHBoxLayout()
        lbl_parity = QtWidgets.QLabel("Parity")
        lbl_parity.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        lbl_parity.setFixedWidth(80)
        parity_row.addWidget(lbl_parity)
        parity_row.addWidget(self.uart_panel.cmbParity)
        layout.addLayout(parity_row)

        # Stop bits row
        stopbits_row = QtWidgets.QHBoxLayout()
        lbl_stopbits = QtWidgets.QLabel("Stop Bits")
        lbl_stopbits.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        lbl_stopbits.setFixedWidth(80)
        stopbits_row.addWidget(lbl_stopbits)
        stopbits_row.addWidget(self.uart_panel.cmbStopBits)
        layout.addLayout(stopbits_row)

        # Slave ID row
        slave_row = QtWidgets.QHBoxLayout()
        lbl_slave = QtWidgets.QLabel("Slave ID")
        lbl_slave.setStyleSheet(f"color:{Colors.TEXT_LABEL}; font-weight:700;")
        lbl_slave.setFixedWidth(80)
        slave_row.addWidget(lbl_slave)
        slave_row.addWidget(self.uart_panel.edSlave)
        layout.addLayout(slave_row)

        # Buttons row
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(self.uart_panel.btnLoad)
        btn_row.addWidget(self.uart_panel.btnRefreshPorts)
        layout.addLayout(btn_row)

        # Connect button (full width)
        layout.addWidget(self.uart_panel.btnConnect)

        # Hide the original UART panel (we're using its widgets in our custom layout)
        self.uart_panel.hide()

        return frame

    def _create_vertical_rd_panel(self):
        """Create a vertical layout wrapper for RD panel widgets"""
        from theme import Colors

        # Create a frame to hold the vertical RD layout
        frame = QtWidgets.QFrame()
        frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        frame.setStyleSheet(
            f"QFrame{{background:{Colors.BG_PANEL}; border:3px solid {Colors.BORDER_PANEL}; border-radius:10px;}} "
            f"QLabel{{color:{Colors.TEXT_LABEL};}}"
        )
        frame.setMinimumWidth(220)
        frame.setMaximumWidth(260)

        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Normal indicator and button row
        normal_row = QtWidgets.QHBoxLayout()
        normal_row.setSpacing(8)
        normal_row.addWidget(self.rd_panel.lblNormalLight)
        normal_row.addWidget(self.rd_panel.btnNormal)
        layout.addLayout(normal_row)

        # Bypass indicator and button row
        bypass_row = QtWidgets.QHBoxLayout()
        bypass_row.setSpacing(8)
        bypass_row.addWidget(self.rd_panel.lblBypassLight)
        bypass_row.addWidget(self.rd_panel.btnBypass)
        layout.addLayout(bypass_row)

        # Mode selector combobox (full width)
        layout.addWidget(self.rd_panel.rdCombo)

        # Switch button (full width)
        layout.addWidget(self.rd_panel.btnSwitch)

        # Hide the original RD panel (we're using its widgets in our custom layout)
        self.rd_panel.hide()

        return frame

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
