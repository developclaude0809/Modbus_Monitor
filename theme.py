"""
Theme configuration for Modbus Monitor
- Color palette management
- UI sizing tokens with scaling support
- Global stylesheet application
"""


class Colors:
    # ------------------------------------------------------------
    # MASTER COLOR PALETTE (Sorted by RGB hex values)
    # ------------------------------------------------------------
    BTN_DANGER_BG     = "#A32424"
    BTN_SUCCESS_HOVER = "#10B97B"
    BTN_SUCCESS_BG    = "#059661"
    MIDNIGHT_NAVY     = "#0F172A"
    DEEP_BLUE         = "#2563EB"
    MIDNIGHT_OCEAN    = "#3282b8"
    COOL_GRAY         = "#1E293B"
    SKY_BLUE          = "#60A5FA"
    MIST_BLUE         = "#38BDF8"
    MINT_GLOW         = "#34D399"
    SOFT_YELLOW       = "#F4F27E"
    CREAM_TINT        = "#FFF5C2"
    ROSE_CORAL        = "#F87171"
    BENIUKON          = "#E98B2A"
    BG_INPUT          = "#334155"
    AKAKUCHIBA        = "#C78550"
    BTN_TEXT_COLOR    = "#FFFFFF"

    # ------------------------------------------------------------
    # SEMANTIC COLORS Contextual mapping for dark UI
    # ------------------------------------------------------------

    # Backgrounds
    BG_APP         = MIDNIGHT_NAVY
    BG_PANEL       = COOL_GRAY
    BG_INPUT_COLOR = BG_INPUT
    BG_BUTTON      = DEEP_BLUE
    BG_HEADER      = COOL_GRAY

    # Text
    TEXT_PRIMARY   = CREAM_TINT
    TEXT_ON_DARK   = CREAM_TINT
    TEXT_LABEL     = MIST_BLUE

    # Borders
    BORDER_NORMAL  = MIST_BLUE
    BORDER_FOCUS   = SKY_BLUE
    BORDER_PANEL   = MIST_BLUE

    # Buttons
    BTN_PRIMARY_BG     = DEEP_BLUE
    BTN_PRIMARY_TEXT   = CREAM_TINT
    BTN_PRIMARY_COLOR  = BTN_TEXT_COLOR
    BTN_PRIMARY_HOVER  = SKY_BLUE

    BTN_DANGER_HOVER   = ROSE_CORAL

    BTN_SUCCESS_BG     = BTN_SUCCESS_BG
    BTN_SUCCESS_HOVER  = BTN_SUCCESS_HOVER

    BTN_SECONDARY_BG   = DEEP_BLUE
    BTN_SECONDARY_HOVER= MIST_BLUE

    # Status & Special Elements
    STATUS_ERROR       = ROSE_CORAL
    STATUS_SUCCESS     = MINT_GLOW
    STATUS_NORMAL      = SOFT_YELLOW

    ROW_NUMBER_BG      = COOL_GRAY
    ROW_NUMBER_TEXT    = CREAM_TINT

    VALUE_DISPLAY_BG   = COOL_GRAY
    VALUE_DISPLAY_TEXT = CREAM_TINT


def clamp(v, lo, hi):
    """Clamp value between lo and hi"""
    return max(lo, min(hi, v))


class UiTokens:
    """UI sizing and spacing tokens with scale support"""

    def __init__(self, scale: float):
        self.scale = scale
        self.s = clamp(scale, 0.9, 1.15)

    def btn_h(self):
        """Button height"""
        return int(clamp(36 * self.s, 32, 44))

    def btn_w(self):
        """Button width"""
        return int(clamp(110 * self.s, 95, 140))

    def padding(self):
        """Standard padding"""
        return int(clamp(8 * self.s, 6, 12))

    def radius(self):
        """Border radius"""
        return int(clamp(8 * self.s, 6, 12))


def apply_stylesheet(app):
    """Apply global stylesheet to the application"""
    css = f"""
    QMainWindow {{
        background-color: {Colors.BG_APP};
        color: {Colors.TEXT_PRIMARY};
    }}

    QLabel {{
        color: {Colors.TEXT_LABEL};
    }}

    QPushButton {{
        background-color: {Colors.BTN_SUCCESS_BG};
        border-radius: 6px;
        padding: 4px 10px;
    }}

    QPushButton:hover {{
        background-color: {Colors.BTN_SUCCESS_HOVER};
    }}
    """
    app.setStyleSheet(css)
