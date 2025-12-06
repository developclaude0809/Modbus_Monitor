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
    """Unified design tokens for consistent UI sizing and responsive layout"""

    def __init__(self, scale: float):
        self.scale = scale
        self.s = clamp(scale, 0.9, 1.15)

    def btn_h(self):
        """Standard button height - scales with display"""
        return int(clamp(36 * self.s, 32, 44))

    def btn_h_large(self):
        """Large button height for prominent controls (motor, reset panels)"""
        return int(clamp(50 * self.s, 42, 58))

    def btn_w(self):
        """Standard button minimum width - responsive"""
        return int(clamp(120 * self.s, 100, 140))

    def input_h(self):
        """Input field height"""
        return int(clamp(34 * self.s, 30, 42))

    def input_h_large(self):
        """Large input field height for prominent inputs"""
        return int(clamp(50 * self.s, 42, 58))

    def pad(self):
        """Padding size"""
        return int(clamp(10 * self.s, 8, 14))

    def padding(self):
        """Standard padding (alias for pad)"""
        return self.pad()

    def gap(self):
        """Gap/spacing size"""
        return int(clamp(8 * self.s, 6, 12))

    def radius(self):
        """Border radius"""
        return int(clamp(8 * self.s, 6, 12))

    def icon(self):
        """Icon size"""
        return int(clamp(20 * self.s, 16, 24))

    def panel_minw(self):
        """Panel minimum width"""
        return int(clamp(520 * self.s, 460, 640))

    def panel_h_control(self):
        """Control panel minimum height (RD, Reset panels)"""
        return int(clamp(80 * self.s, 70, 95))

    def combo_w(self):
        """Combo box minimum width"""
        return int(clamp(140 * self.s, 120, 160))

    # Font size tokens - scale with display DPI
    def font_small(self):
        """Small font size (10px base)"""
        return int(clamp(10 * self.s, 9, 12))

    def font_normal(self):
        """Normal font size (14px base)"""
        return int(clamp(14 * self.s, 12, 16))

    def font_medium(self):
        """Medium font size (16px base)"""
        return int(clamp(16 * self.s, 14, 18))

    def font_large(self):
        """Large font size (22px base - for combo/inputs)"""
        return int(clamp(22 * self.s, 19, 26))

    def font_xlarge(self):
        """Extra large font size (24-26px base - for prominent buttons)"""
        return int(clamp(25 * self.s, 22, 29))


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
