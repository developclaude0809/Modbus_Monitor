# Modbus 0x04 Data Definition (.ddata) — Format and Loading Logic

This document explains how the app loads Modbus 0x04 Input Register data definitions from `*.ddata` files, the expected file format, search/fallback rules, and how the UI applies the definitions.

## File Locations and Names
- Folder: `./setting`
- Preferred, per-mode filenames: `__address_04def_[MODE].ddata` (e.g. `__address_04def_Normal.ddata`)
- Generic fallback filename: `__address_04def.ddata`
- Persisted selections: `setting/LoadSettings.dmem`

## Where Loading Happens (Code)
- Startup memory/init and pattern fallback: `app.py:3850`–`3916`, `app.py:3882`–`3900`
- Apply current mode’s file: `app.py:3918`–`3934` (`_apply_04_for_current_mode`)
- Mode-aware load with pattern fallback: `app.py:3936`–`4030` (`_load_input_defs`)
- Explicit file load (12 inputs): `app.py:4107`–`4173` (`_load_input_defs_from_file`)
- Update UI titles after load: `app.py:4031`–`4038` (`_update_input_titles`)
- Render values according to definition: `app.py:4473`–`4539` (`_render_input04`)

## Load Order (High-Level)
1. If the user previously selected files in the Load Settings dialog, those filenames are stored in `LoadSettings.dmem` and applied at startup per current mode.
2. If nothing valid is found from memory, the app tries pattern-based files in `./setting`:
   - First: `__address_04def_[MODE].ddata`
   - Then: `__address_04def.ddata`
3. If still not found, defaults are used for all inputs.
4. When the mode changes, the app resolves the file for that mode and reloads definitions.

Notes:
- The explicit loader `_load_input_defs_from_file(...)` reads up to 12 inputs (`IN0..IN11`).
- The pattern-based loader `_load_input_defs(mode)` uses up to 8 inputs (`IN0..IN7`). This is intentional in current code; use the explicit loader for full 12-input files.

## The .ddata File Format (CSV-like)
Each non-empty line defines one input register in order. Fields are comma-separated.

Format per line:
1) Title, 2) Format, 3) Ratio, 4) Show

Details:
- Title: Text shown on the UI label for that input (e.g. `Motor Temp`).
- Format (`fmt`): One of `value`, `bitstatus`, `valstatus`.
- Ratio: Floating-point multiplier applied to the raw value (default `1.0`).
- Show: Depends on `fmt` (see below).

Supported formats and `show` semantics:
- `value`
  - `show`: `int16` or `uint16` (default `int16`).
  - Logic: Convert raw value to signed (`int16`) or unsigned (`uint16`), multiply by ratio, and display. If the result is an integer, trailing `.0` is suppressed.
- `bitstatus`
  - `show`: `1/0` or a `|`-separated list of labels, from MSB to LSB, up to 16 entries.
  - Logic: If raw value is `0`, display `Normal`. Otherwise, if `1/0`, show a 16-bit binary string. If label list provided, show a comma-separated list of active bit labels (MSB→LSB). Unlabeled bits are skipped.
- `valstatus`
  - `show`: `|`-separated labels list, up to 16 entries.
  - Logic: Interpret the raw value as a 0-based index into the label list; out-of-range shows `NA`.

Parsing defaults and guards:
- Unknown `fmt` falls back to `value`.
- Missing/invalid `ratio` falls back to `1.0`.
- Missing/invalid `show` falls back per the rules above.
- Excess labels are truncated to 16.

## Examples

Eight inputs (mixed formats):
```
Motor Temp,value,0.1,int16
System Flags,bitstatus,,Overheat|FanFail|DoorOpen|PSU1|PSU2
Mode,valstatus,,Standby|Normal|Bypass|Inverter
Analog In,value,1.0,uint16
Reserved,value,,
Fault Bits,bitstatus,,1/0
Speed Command,value,0.01,uint16
Status,valstatus,,OK|WARN|ERROR
```

Twelve inputs (explicit loader):
```
IN0 Title,value,1.0,int16
IN1 Title,value,1.0,int16
IN2 Title,bitstatus,,Label15|Label14|...|Label0
IN3 Title,valstatus,,State0|State1|State2
IN4 Title,value,0.1,uint16
IN5 Title,value,1.0,int16
IN6 Title,value,1.0,int16
IN7 Title,value,1.0,int16
IN8 Title,value,1.0,int16
IN9 Title,value,1.0,int16
IN10 Title,value,1.0,int16
IN11 Title,value,1.0,int16
```

## How the UI Applies Definitions
- After loading definitions, `app.py:4031` updates the input label titles.
- During polling updates, `app.py:4473` renders each register value using the loaded definition:
  - `value`: signed/unsigned with ratio and number formatting
  - `bitstatus`: `Normal` if zero, else 16-bit or active labels
  - `valstatus`: map index to label or `NA`

## Selecting Files via the Dialog
- Open the dialog to select files: calls `open_load_dialog()` → `LoadSettingsDialog`.
- The dialog scans `./setting` for `*.ddata` once and offers the same list for all selectors.
- 03 and each 04 mode can be set independently; selections persist to `LoadSettings.dmem`.
- On apply, the app loads the 03 file and the current mode’s 04 file, and stores per-mode filenames for future mode switches.

## Mode Switching Behavior
- Current mode determines which 04 file is active.
- On mode change, `_apply_04_for_current_mode()` resolves from saved filenames; if missing, pattern fallback is used.
- If no file is found, defaults are used (labels `INx`, `value`, ratio `1.0`, `int16`).

## Quick Checklist for New Files
- Place the file under `./setting/`.
- Name it `__address_04def_[MODE].ddata` to benefit from automatic switching.
- Ensure each line uses: `Title,Format,Ratio,Show`.
- Keep labels to max 16 and ordered MSB→LSB for `bitstatus`.
- Prefer 12 lines if you intend to define `IN0..IN11` and use explicit loading.

