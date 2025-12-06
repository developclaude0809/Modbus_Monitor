"""
Panels package for Modbus Monitor V1
Each panel is a self-contained UI component with its own signals.
"""

from .uart_panel import UARTPanel
from .motor_panel import MotorPanel
from .rw_panel import RWPanel
from .rd_panel import RDPanel
from .reset_panel import ResetPanel
from .plot_panel import PlotPanel

__all__ = [
    'UARTPanel',
    'MotorPanel',
    'RWPanel',
    'RDPanel',
    'ResetPanel',
    'PlotPanel',
]
