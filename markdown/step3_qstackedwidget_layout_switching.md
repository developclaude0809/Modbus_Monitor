# Step 3 — Add New Layout Page and Enable Layout Switching (QStackedWidget)

This document describes **Step 3** of the multi-layout refactor plan:

> Add **the new layout (Layout V2)** as a second page in `QStackedWidget`,  
> connect it to the centralized update functions,  
> and provide a safe mechanism to switch between layouts without breaking existing behavior.

---

# 🎯 Goals of Step 3
- Introduce a **new layout page (V2)** into the existing `QStackedWidget`.
- Keep the current classic layout as **page 0**.
- Ensure **all UI updates** flow through centralized update functions built in Step 1.
- Allow **runtime switching** between layouts.
- Avoid code duplication and UI update duplication.
- Guarantee existing behavior is preserved.

---

# 📐 Required Modifications

## 1. Create the New Layout Page (Layout V2)

Add a function:

```python
def _build_ui_v2(self) -> QtWidgets.QWidget:
    root = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(root)

    # Build new UI sections (panels, controls, plots, etc.)
    # Widgets here must be NEW instances, not reused from V1.

    return root
```

**Important Rules**
- Widgets from V1 **must not** be reused in V2.
- V2 must rely on **centralized UI update functions**, not direct logic.
- V2 must have its own widget list, e.g.:
  - `self.rowValues_v2`
  - `self.inputRegValues_v2`
  - `self.plot_lines_v2`
- But these new widgets must be updated through Step 1 functions.

---

## 2. Add V2 to QStackedWidget

In `__init__`:

```python
root_v1 = self._build_ui()
root_v2 = self._build_ui_v2()

self.stack = QtWidgets.QStackedWidget()
self.stack.addWidget(root_v1)   # Page 0
self.stack.addWidget(root_v2)   # Page 1

self.setCentralWidget(self.stack)
```

This completes the **two-page layout system**.

---

## 3. Integrate V2 with Centralized Update Functions

All Step 1 update functions must be extended to also update V2 widgets.

Example:

```python
def _update_03_row_ui(self, index, value, error):
    # Update V1:
    self.rowValues[index].setText(...)

    # Update V2 (if widgets exist):
    if hasattr(self, "rowValues_v2"):
        self.rowValues_v2[index].setText(...)
```

Same applies to:
- `_update_04_inputs_ui`
- `_update_device_info_from_registers`
- `_update_alarm_display`
- `_on_plot_data`
- `_on_rr_frame`

**This avoids duplicating logic**, ensuring V2 always stays synced.

---

## 4. Add Layout Switching API

Add or expand:

```python
def switch_layout(self, index: int):
    self.stack.setCurrentIndex(index)
    self.adjustSize()
```

Options for switching:
- Menu entry (View > Classic / V2)
- Toolbar button
- Keyboard shortcut

---

# 🧪 Behavioral Requirements

### These behaviors must remain unchanged:
- Polling (03/04)
- Plotting (03, RR Mode)
- Buttons and controls
- All dialogs (Device Info, Alarm Log)
- Worker threads & signals
- Status bar updates
- Mode switching logic

Only the layout appearance changes.

---

# ✔ Verification Checklist

### Layout Switching
- [ ] Can switch from V1 to V2 without errors
- [ ] Can switch during polling
- [ ] Can return to V1 without glitches
- [ ] Window resizes correctly for each layout

### Data Synchronization
- [ ] 03 values appear correctly in V1 & V2
- [ ] 04 values show correctly in both layouts
- [ ] Device Info unaffected
- [ ] Alarm Log unaffected
- [ ] Plot lines update in V2

### Stability
- [ ] No crash from missing widgets
- [ ] No duplicated logic
- [ ] No regressions in classic layout

---

# 📁 Step 4 Preview

Once V2 is stable:

> Step 4 focuses on **optimizing V2**,  
> reducing redundancy between V1/V2,  
> and preparing to slowly deprecate V1.

