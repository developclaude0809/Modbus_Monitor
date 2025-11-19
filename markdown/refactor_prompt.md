# Refactor Prompt — Centralized UI Update Functions (Markdown Version)

## Objective
Refactor the PyQt5 application to consolidate all UI updates into centralized update functions, without modifying the existing UI layout or affecting any communication logic.

## Goals
- Centralize all UI updates into dedicated update functions.
- Remove direct widget manipulation scattered throughout the code.
- Keep all behavior identical.
- Prepare for future alternate UI layouts without code duplication.

## Requirements

### 1. Centralize UI update operations
Create dedicated update methods responsible for updating the UI based on structured data, such as:

```python
update_03_values(data: list[int])
update_04_values(data: list[int])
update_device_info(data: dict)
update_alarm_display(index: int, values: list[int])
update_plot_data(ch_index: int, x: float, y: float)
```

These functions must become the exclusive mechanism for updating UI widgets.

### 2. Replace scattered widget updates
Remove direct widget operations such as:

- `self.inputRegValues[i].setText(...)`
- `self.data_labels[idx].setText(...)`
- `self.lblDeviceInfoFirmware.setText(...)`
- Direct plot canvas manipulations in the UI layer

Refactor all such occurrences to call the new centralized update functions instead.

### 3. Preserve 100% of current behavior
The refactor must not modify:

- Widget layout  
- Stylesheets  
- Timing behavior  
- Modbus communication logic  
- Worker thread behavior  
- Any features or UI elements  

The application must look and behave exactly the same from the user’s perspective.

### 4. Introduce internal UI state storage
Create internal structures to store the latest values, for example:

```python
self.state_03 = [...]
self.state_04 = [...]
self.state_device_info = {...}
self.state_alarm = [...]
self.state_plot = {...}
```

Centralized update functions should:

1. Update the internal state  
2. Update the UI based on that state  

### 5. Ensure future layouts can reuse the same update functions
Design the update functions so they are layout-agnostic, allowing future UI versions (e.g., Layout V2) to reuse the same logic by reading from the internal state.

### 6. Maintain thread-safety
UI updates must continue to:

- Be triggered from Qt signals  
- Execute on the main UI thread  
- Avoid race conditions  
- Remain compatible with PollWorker, PlotWorker, and any background threads  

## Output Requirements
The AI should output:

- Modified code with the new centralized update functions  
- Adjusted UI update logic routed through these functions  
- Definitions for the new internal state structures  
- Any additional minor reorganization required to preserve identical behavior  

No new UI components or layout changes should be introduced.
