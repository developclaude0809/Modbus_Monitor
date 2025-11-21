# Step 2 — Introduce QStackedWidget (Without Changing Existing Layout)

This document describes **Step 2** of the UI refactor plan:

> Add a QStackedWidget as the main container, but initially place **only the existing classic layout** inside it.  
> No behavior, appearance, or layout should change.

---

# **🎯 Goals of Step 2**
- Introduce a `QStackedWidget` as the MainWindow's central widget.
- Move the **existing full UI** (classic layout) into page index 0.
- Do **not** modify any UI:
  - No repositioning
  - No size change
  - No new widgets
  - No new layout logic
- Maintain 100% backward-compatible behavior.
- Prepare the architecture so new layouts can be added later (page 1, page 2, etc.).

---

# **📐 Required Modifications**

## **1. Modify `_build_ui()` to return the root classic layout widget**
Example:

```python
def _build_ui(self) -> QWidget:
    root = QWidget()
    main_layout = QVBoxLayout(root)
    # ... build everything exactly as before ...
    return root
```

This root widget becomes **page 0** in the stacked widget.

---

## **2. Modify MainWindow `__init__` to introduce QStackedWidget**
Replace the old:

```python
root = self._build_ui()
self.setCentralWidget(root)
```

with:

```python
root = self._build_ui()

self.stack = QStackedWidget()
self.stack.addWidget(root)       # Page 0: Classic layout

self.setCentralWidget(self.stack)
```

Nothing else changes.

---

## **3. Add a helper function for future layout switching**

```python
def switch_layout(self, index: int):
    self.stack.setCurrentIndex(index)
    self.adjustSize()  # Allow window to resize naturally for future pages
```

Do **not** call this anywhere yet.  
It only prepares the architecture for Step 3.

---

# **⚙️ Behavioral Requirements**

- The program must look and behave *exactly* the same as before.
- All widgets must still exist with the same references:
  - `self.rowValues`
  - `self.inputRegValues`
  - `self.plot_canvas`
  - all dialogs, panels, frames, etc.
- All signals/slots must operate the same.
- Polling, plotting, dialogs, events → unchanged.

If the user cannot notice any difference, Step 2 is successful.

---

# **🧪 Verification Checklist**

Use this list to verify Step 2 was implemented correctly:

### ✔ UI loads normally  
### ✔ Window size and layout identical  
### ✔ Buttons, panels, plots work normally  
### ✔ Polling (03/04) functions normally  
### ✔ Plots update normally  
### ✔ Device Info & Alarm Log open normally  
### ✔ No attribute missing errors  
### ✔ No resizing glitches  
### ✔ No visual shifts  
### ✔ No extra whitespace or padding  

If all above pass: **Step 2 complete**.

---

# **📁 Next Step (Step 3 Preview)**

After Step 2 is verified stable, Step 3 will be:

> Introduce the **new layout page** (page 1) into QStackedWidget,  
> connect it to the centralized update functions,  
> and allow switching between both layouts.

Step 2 is the foundation for this.

