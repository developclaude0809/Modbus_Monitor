# View Switching Feature (F9)

## Overview
The application now supports switching between two views:
- **V1 (Full View)**: Complete interface with Plot panel and RR mode
- **V2 (Compact View)**: Simplified interface without Plot/RR functionality

## Usage
Press **F9** at any time to toggle between views.

## View Comparison

### V1 - Full View (Default)
```
├─ UART Panel (connection settings)
├─ Motor Control Panel
├─ RW Panel (read/write registers + 04 input registers)
├─ RD Panel (normal/bypass control)
├─ Reset Panel
└─ Plot Panel (with 03 mode & RR mode support)
   ├─ 4-channel plotting
   ├─ Mode switch (03/RR)
   ├─ Real-time data visualization
   └─ Matplotlib toolbar
```

### V2 - Compact View
```
├─ UART Panel (connection settings)
├─ Motor Control Panel
│  └─ Left column
└─ RD Panel + Reset Panel
   └─ Right column (stacked vertically)
└─ RW Panel (read/write registers + 04 input registers)
   └─ Full width at bottom
```

## Implementation Details

### Files Modified
1. **app.py**
   - Added `MainView_V1` and `MainView_V2` imports
   - Added `current_view` state variable
   - Implemented `keyPressEvent()` to capture F9
   - Implemented `_switch_view()` method
   - Added safety checks to plot-related methods:
     - `_toggle_plotting()`
     - `_start_plotting()`
     - `_update_plot()`
     - `update_draw_button()`
     - `_switch_to_rr_mode()`
     - `_switch_to_03_mode()`
   - Conditional widget initialization in `_build_ui()`

2. **view_v2.py** (New File)
   - Simplified MainView without PlotPanel
   - Compact 3-column layout
   - All essential panels retained

### View Switching Process
When F9 is pressed:
1. Stop all active workers (polling, plotting, RR mode)
2. Close serial connection
3. Save current state (selected COM port)
4. Toggle `current_view` between "v1" and "v2"
5. Create new view instance
6. Rebuild UI completely
7. Restore COM port selection
8. Reload definitions and settings
9. Display status message

### Safety Features
- All plot-related methods check for widget existence
- Graceful degradation when plot widgets are None
- Error handling with traceback output
- Window update forced after view switch

## Benefits of V2 View
- **Faster startup**: No matplotlib initialization
- **Lower memory usage**: No plot data structures
- **Simpler interface**: Focus on core Modbus communication
- **Better for simple testing**: Quick read/write operations
- **More screen space**: RW panel gets full width at bottom

## Technical Notes
- View switching preserves serial connection settings
- Definition files are reloaded after switch
- 03 memory addresses are restored
- Input register titles are refreshed
- No data loss during switch (04 input registers maintained)
