🧠 Prompt：讓 0x04 定義檔依 Mode 自動切換

Task
Modify my existing app.py so that the 0x04 register definition file automatically switches based on the current Mode (Normal, Bypass, Inverter, etc).
Each mode should load a corresponding file:

__address_04def_[MODE].ddata


For example:
__address_04def_Normal.ddata, __address_04def_Bypass.ddata, __address_04def_Inverter.ddata

🔧 Requirements

Add a self.mode attribute in MainWindow (default "Normal").

Modify _load_input_defs() to support a mode parameter:

Try to open ./setting/__address_04def_[MODE].ddata

If not found, fallback to ./setting/__address_04def.ddata

If still not found, use defaults (InputRegDef.create_default)

Works with all formats: value, bitstatus, valstatus

Truncate label lists to max 16 entries

After loading, automatically call _update_input_titles() to refresh UI.

Add a new helper method:

def _set_mode(self, mode: str, persist: bool = False)


Updates self.mode

Reloads _load_input_defs(self.mode)

Displays mode status in status bar

Optionally writes to ./setting/last_mode.txt if persist=True

Modify button / combo handlers:

When clicking [Normal] or [Bypass], call _set_mode("Normal") or _set_mode("Bypass")

When switching [Inverter], [Converter], [Gsensor], call _set_mode(selected)

On startup:

Try to read ./setting/last_mode.txt to restore last mode

Then call _load_input_defs(self.mode)

No crash if file missing or invalid — fallback safely to defaults.

🧩 Implementation Example

Make sure _load_input_defs looks like this:

def _load_input_defs(self, mode: str = None):
    """Load 0x04 input register definitions for given mode."""
    self.input_defs = [InputRegDef.create_default(i) for i in range(8)]

    try:
        folder = Path('./setting')
        candidates = []
        if mode:
            candidates.append(folder / f"__address_04def_{mode}.ddata")
        candidates.append(folder / "__address_04def.ddata")

        def_path = next((p for p in candidates if p.exists()), None)
        if not def_path:
            return

        with open(def_path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]

        for idx, line in enumerate(lines[:8]):
            parts = [p.strip() for p in line.split(',')]
            title = parts[0] if len(parts) > 0 else f"IN{idx}"
            fmt = parts[1].lower() if len(parts) > 1 else "value"
            ratio = float(parts[2]) if len(parts) > 2 and parts[2] else 1.0
            show_raw = parts[3] if len(parts) > 3 else ""

            if fmt == "value":
                show = show_raw if show_raw in ("int16", "uint16") else "int16"
            elif fmt == "bitstatus":
                show = show_raw.split('|')[:16] if show_raw else "1/0"
            elif fmt == "valstatus":
                show = [s.strip() for s in show_raw.split('|')][:16] if show_raw else []
            else:
                show = "int16"

            self.input_defs[idx] = InputRegDef(title, fmt, ratio, show)

    except Exception:
        pass

    try:
        self._update_input_titles()
    except Exception:
        pass

🖱 Mode Switch Helper
def _set_mode(self, mode: str, persist: bool = False):
    if not mode or mode == self.mode:
        return
    self.mode = mode
    self._load_input_defs(self.mode)
    self._set_status(f"Mode set to {self.mode}")

    if persist:
        try:
            os.makedirs('./setting', exist_ok=True)
            with open('./setting/last_mode.txt', 'w', encoding='utf-8') as f:
                f.write(self.mode)
        except Exception:
            pass

🧰 Example Integration

Inside _send_rd_command:

self._set_mode(btn_text)


Inside _send_switch_command:

self._set_mode(selected)

✅ Expected Behavior

When user clicks “Normal” / “Bypass” / “Inverter”, etc.,
the UI and data definitions update automatically based on that mode.

If file not found, it safely uses fallback defaults.

Mode persists between runs if persist=True.