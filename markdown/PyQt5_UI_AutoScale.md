# 🧩 PyQt5 自適應視窗設計方案（實際實作版）

## 🎯 目標
讓介面能在不同解析度下：
- 預先計算螢幕縮放比例，供特定功能使用（如圖表縮放）
- **保留現有精心設計的主題樣式**
- 提供可選的 Design Tokens 架構，供未來擴充

---

## ⚠️ 重要經驗教訓

### 為什麼不全面套用自動縮放？
在實作過程中發現：
1. **現有主題已經很完善**：app.py 已有精心設計的深色主題，包含顏色、邊框、hover 效果等
2. **強制覆蓋會破壞視覺**：用通用規則覆蓋 stylesheet 會導致：
   - 顏色主題丟失（Midnight Navy、Sky Blue、Soft Yellow 等）
   - 按鈕 hover 效果消失
   - 輸入框選取顏色錯誤
   - 整體視覺不一致
3. **強制尺寸限制會破壞排版**：對所有控件設 min/max height 會：
   - 破壞原有的 layout 邏輯
   - 造成控件擠壓或空白過大
   - 與 QSplitter、ScrollArea 等佈局衝突

---

## ✅ 實際採用方案：輕量化縮放架構

### 設計原則
1. **計算縮放比例但不強制套用**：保留 `compute_ui_scale()` 計算螢幕比例，存在 `w.ui_scale` 供需要的功能使用
2. **保留 Design Tokens 基礎設施**：`UiTokens` 類別存在但不啟用，供未來有需要時使用
3. **完全保留現有主題**：不覆蓋任何 stylesheet，不強制控件尺寸

---

## ⚙️ 實際實作程式碼

### 1️⃣ 計算比例縮放值（已實作）
```python
def clamp(val, lo, hi):
    """Clamp value between low and high bounds"""
    return max(lo, min(hi, val))


def compute_ui_scale(app, base_w=2560, base_h=1440, lo=0.85, hi=1.25):
    """Compute UI scale factor based on screen resolution"""
    screen = app.primaryScreen()
    geom = screen.availableGeometry()
    sw, sh = geom.width(), geom.height()
    s = min(sw / float(base_w), sh / float(base_h))
    return max(lo, min(hi, s))
```
**位置**：`app.py:977-988`
**用途**：計算螢幕相對於基準解析度（2560x1440）的縮放比例，限制在 0.85-1.25 之間

---

### 2️⃣ 定義統一的設計 Tokens（已實作但未啟用）
```python
class UiTokens:
    """Unified design tokens for consistent UI sizing"""

    def __init__(self, scale: float):
        self.scale = scale
        self.s = clamp(scale, 0.9, 1.15)

    def btn_h(self):
        """Button height"""
        return int(clamp(36 * self.s, 32, 44))

    def input_h(self):
        """Input field height"""
        return int(clamp(34 * self.s, 30, 42))

    def pad(self):
        """Padding size"""
        return int(clamp(10 * self.s, 8, 14))

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
```
**位置**：`app.py:991-1024`
**狀態**：已實作但未使用，保留供未來擴充

---

### 3️⃣ 樣式套用函數（已停用）
```python
def style_consistent(app: QtWidgets.QApplication, tokens: UiTokens):
    """Apply consistent styling based on UI tokens (minimal override to preserve theme)"""
    # Only apply non-intrusive scaling adjustments, don't override the main theme
    pass  # Keep existing theme intact
```
**位置**：`app.py:1027-1030`
**狀態**：已停用（pass），避免覆蓋現有主題

---

### 4️⃣ 控件尺寸套用函數（已停用）
```python
def apply_control_sizes(root: QtWidgets.QWidget, tokens: UiTokens):
    """Apply size constraints to all controls based on UI tokens"""
    # Disabled: The existing UI already has good sizing
    # Only apply if there are specific scaling issues
    pass
```
**位置**：`app.py:1033-1037`
**狀態**：已停用（pass），避免破壞現有 layout

---

### 5️⃣ 在主程式中整合（最小化實作）
```python
# Compute UI scale (available for future use, e.g., plot scaling)
scale = compute_ui_scale(app)

w = MainWindow()
w.setWindowIcon(QIcon(ico_path))
w.ui_scale = scale  # Store scale for plot scaling if needed

w.show()
```
**位置**：`app.py:3124-3131`
**實作內容**：
- 計算 `scale` 值
- 儲存在 `w.ui_scale` 屬性中
- **不呼叫** `style_consistent()`
- **不呼叫** `apply_control_sizes()`
- 完全保留現有主題和佈局

---

## 🎨 如何在特定功能中使用縮放比例

如果你需要在某個功能（如圖表、自訂控件）中使用縮放比例：

### 方法 1：直接存取 ui_scale 屬性
```python
class MainWindow(QtWidgets.QMainWindow):
    def some_plotting_function(self):
        # Access the stored scale
        scale = self.ui_scale

        # Use it for plot sizing
        fig_width = 12 * scale
        fig_height = 8 * scale

        # Or for custom widget sizing
        custom_size = int(100 * scale)
```

### 方法 2：使用 UiTokens（如果需要）
```python
# In specific places where you need token-based sizing
tokens = UiTokens(self.ui_scale)

# Use tokens for specific elements
custom_button.setMinimumHeight(tokens.btn_h())
layout.setSpacing(tokens.gap())
layout.setContentsMargins(tokens.pad(), tokens.pad(), tokens.pad(), tokens.pad())
```

---

## 📋 現有主題樣式（請勿覆蓋）

app.py 中已有完整的主題定義（`app.py:3082-3145`），包含：

```python
app.setStyleSheet(f"""
    QWidget {{
        background-color: {Colors.COOL_GRAY};
        color: {Colors.TEXT_PRIMARY};
        font-family: Nunito, Segoe UI, Arial, Helvetica, sans-serif;
        font-size: 14px;
    }}

    QFrame {{
        background-color: {Colors.BG_PANEL};
        border: 1px solid {Colors.BORDER_PANEL};
        border-radius: 10px;
    }}

    QLineEdit, QComboBox {{
        background-color: {Colors.BG_INPUT};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER_NORMAL};
        border-radius: 6px;
        padding: 6px 8px;
        selection-background-color: {Colors.SOFT_YELLOW};
        selection-color: {Colors.MIDNIGHT_NAVY};
    }}

    QPushButton {{
        background-color: {Colors.BTN_PRIMARY_BG};
        color: {Colors.BTN_PRIMARY_TEXT};
        font-weight: 700;
        border: 1px solid {Colors.BORDER_NORMAL};
        border-radius: 8px;
        padding: 8px 12px;
    }}
    QPushButton:hover {{
        background-color: {Colors.AKAKUCHIBA};
        border-color: {Colors.BORDER_FOCUS};
    }}

    /* ...and more */
""")
```

**⚠️ 這些樣式已經過精心設計，不應該被覆蓋！**

---

## ✅ 實際效果

### 已實現
- ✅ `ui_scale` 屬性可用於需要縮放的特定功能
- ✅ `UiTokens` 基礎設施已就緒，可選擇性使用
- ✅ 完全保留現有主題和視覺設計
- ✅ 不破壞任何現有 layout 和排版

### 未實現（故意不做）
- ❌ 不全面套用自動縮放（會破壞主題）
- ❌ 不強制控件尺寸（會破壞 layout）
- ❌ 不覆蓋 stylesheet（會丟失顏色主題）

---

## 💡 建議使用場景

### ✅ 適合使用 ui_scale 的場景
1. **圖表繪製**：調整 matplotlib figure 大小
2. **自訂繪圖控件**：QPainter 繪製時的座標縮放
3. **動態生成的控件**：根據螢幕大小調整尺寸
4. **特定區塊的間距**：用 `tokens.gap()` 設定 layout spacing

### ❌ 不適合的場景
1. **全域 stylesheet 覆蓋**：會破壞現有主題
2. **批量修改所有控件尺寸**：會破壞 layout
3. **修改已定義好的控件樣式**：會造成不一致

---

## 📖 總結

這個實作是「**輕量化、可選擇性使用**」的縮放架構：
- 保留了完整的縮放計算和 Design Tokens 基礎設施
- 但**不強制套用**，避免破壞現有精心設計的 UI
- 提供 `w.ui_scale` 給需要的功能使用
- 保持程式碼乾淨、主題完整

**核心理念**：工具可用但不強制，保護現有設計的完整性。
