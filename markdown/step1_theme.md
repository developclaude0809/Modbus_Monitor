
# Step 1 — Extract `theme.py`
UI/UX 重構第一步：將顏色與尺寸 Token 從主程式 `app.py` 拆分出去

## 目的
把程式中的以下元素統一抽離到獨立檔案 `theme.py`：

- 顏色管理（Colors）
- 尺寸/間距 Token（UiTokens）
- 全域樣式（Stylesheet）

## theme.py

```python
class Colors:
    BTN_DANGER_BG     = "#A32424"
    BTN_SUCCESS_HOVER = "#10B97B"
    BTN_SUCCESS_BG    = "#059661"

    MIDNIGHT_NAVY     = "#0F172A"
    DEEP_BLUE         = "#2563EB"
    COOL_GRAY         = "#1E293B"

    SKY_BLUE          = "#60A5FA"
    MIST_BLUE         = "#38BDF8"
    MINT_GLOW         = "#34D399"
    SOFT_YELLOW       = "#F4F27E"
    CREAM_TINT        = "#FFF5C2"
    ROSE_CORAL        = "#F97373"

    BG_APP       = MIDNIGHT_NAVY
    BG_PANEL     = COOL_GRAY
    TEXT_PRIMARY = CREAM_TINT
    TEXT_LABEL   = MIST_BLUE


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class UiTokens:
    def __init__(self, scale: float):
        self.scale = scale
        self.s = clamp(scale, 0.9, 1.15)

    def btn_h(self):
        return int(clamp(36 * self.s, 32, 44))

    def btn_w(self):
        return int(clamp(110 * self.s, 95, 140))

    def padding(self):
        return int(clamp(8 * self.s, 6, 12))

    def radius(self):
        return int(clamp(8 * self.s, 6, 12))


def apply_stylesheet(app):
    css = f\"\"\"
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
    \"\"\"
    app.setStyleSheet(css)
```

## main.py 整合方式

```python
import theme

app = QtWidgets.QApplication(sys.argv)
theme.apply_stylesheet(app)

tokens = theme.UiTokens(scale=1.0)
```
