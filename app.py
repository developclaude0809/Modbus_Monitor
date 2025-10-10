"""
Enhanced Modbus RTU Controller with Modern UI
- Clean, intuitive interface design
- Proper threading with thread-safe UI updates
- Modbus protocol support with register monitoring
- Auto-polling with configurable intervals
- Address definition file support
"""

import threading
import time
import struct
import os
from pathlib import Path
from typing import Optional, List, Tuple, Any
from datetime import datetime

import customtkinter as ctk
from tkinter import filedialog, messagebox

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    import sys
    sys.exit("Missing pyserial. Install: pip install pyserial")

# Set appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ==================== Custom Scrollable ComboBox (Beautiful Version) ====================
# ==================== Fixed Custom Scrollable ComboBox ====================
class ScrollableCombo(ctk.CTkFrame):
    """Beautiful scrollable dropdown with smooth animations and colorful highlighting"""
    
    def __init__(self, master, values: List[str] = None, width: int = 200,
                 max_dropdown_height: int = 300, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        
        self._values: List[str] = values if values else []
        self._width = width
        self._max_dropdown_height = max_dropdown_height
        self._current: str = self._values[0] if self._values else ""
        
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        
        # Main display entry (readonly) - yellow-white background with light-blue border
        self._entry = ctk.CTkEntry(
            self,
            width=self._width,
            height=32,
            font=ctk.CTkFont(size=13),
            state="readonly",
            fg_color=("#fffacd", "#2a2a2a"),
            text_color=("black", "white"),
            border_color=("#87ceeb", "#5dade2"),
            border_width=2
        )
        self._entry.grid(row=0, column=0, sticky="ew")
        
        # Dropdown arrow button with light blue
        self._btn = ctk.CTkButton(
            self,
            text="▼",
            width=35,
            height=32,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._toggle_dropdown,
            fg_color=("#87ceeb", "#5dade2"),
            hover_color=("#5dade2", "#3b9cd9"),
            text_color=("black", "white")
        )
        self._btn.grid(row=0, column=1, padx=(4, 0))
        
        # Dropdown window reference
        self._dropdown: Optional[ctk.CTkToplevel] = None
        self._scroll_frame: Optional[ctk.CTkScrollableFrame] = None
        self._buttons: List[ctk.CTkButton] = []
        
        # Set initial value
        self.set(self._current if self._current else (self._values[0] if self._values else ""))
        
        # Mouse wheel support for cycling values
        self._entry.bind("<MouseWheel>", self._on_wheel, add="+")
        self._entry.bind("<Button-4>", self._on_wheel, add="+")
        self._entry.bind("<Button-5>", self._on_wheel, add="+")
        self._btn.bind("<MouseWheel>", self._on_wheel, add="+")
        self._btn.bind("<Button-4>", self._on_wheel, add="+")
        self._btn.bind("<Button-5>", self._on_wheel, add="+")
        
        # Click entry to open dropdown
        self._entry.bind("<Button-1>", lambda e: self._toggle_dropdown(), add="+")
    
    def set(self, value: str):
        """Set current value"""
        self._current = value
        self._entry.configure(state="normal")
        self._entry.delete(0, "end")
        self._entry.insert(0, value)
        self._entry.configure(state="readonly")
    
    def get(self) -> str:
        """Get current value"""
        return self._current
    
    def configure(self, **kwargs):
        """Configure widget"""
        if "values" in kwargs:
            self._values = list(kwargs["values"]) if kwargs["values"] else []
            if self._current not in self._values and self._values:
                self._current = self._values[0]
                self.set(self._current)
    
    def cget(self, key: str):
        """Get configuration value"""
        if key == "values":
            return tuple(self._values)
        return super().cget(key)
    
    def _toggle_dropdown(self):
        """Toggle dropdown visibility"""
        if self._dropdown and self._dropdown.winfo_exists():
            self._close_dropdown()
        else:
            self._open_dropdown()
    
    def _open_dropdown(self):
        """Open beautiful dropdown menu"""
        if not self._values:
            return
        
        # Create toplevel window
        self._dropdown = ctk.CTkToplevel(self)
        self._dropdown.overrideredirect(True)
        
        # CRITICAL FIX: Set transient and lift attributes
        self._dropdown.transient(self.winfo_toplevel())
        self._dropdown.attributes('-topmost', True)  # Force on top
        
        # Calculate position - ensure widget is updated
        self.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        
        # Dynamic height based on items (max 10 items visible)
        item_height = 36
        visible_items = min(len(self._values), 10)
        height = min(visible_items * item_height + 10, self._max_dropdown_height)
        
        dropdown_width = self._width + 39
        
        # Ensure dropdown stays on screen
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        if x + dropdown_width > screen_width:
            x = screen_width - dropdown_width - 10
        if y + height > screen_height:
            y = self.winfo_rooty() - height - 2  # Show above if not enough space below
        
        self._dropdown.geometry(f"{dropdown_width}x{height}+{x}+{y}")
        
        # Scrollable frame with beautiful styling
        self._scroll_frame = ctk.CTkScrollableFrame(
            self._dropdown,
            width=dropdown_width - 20,
            fg_color=("gray90", "gray20"),
            corner_radius=8
        )
        self._scroll_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Color palette for items
        colors = [
            ("#3b82f6", "#2563eb"),  # Blue
            ("#8b5cf6", "#7c3aed"),  # Purple
            ("#ec4899", "#db2777"),  # Pink
            ("#f59e0b", "#d97706"),  # Amber
            ("#10b981", "#059669"),  # Green
            ("#06b6d4", "#0891b2"),  # Cyan
        ]
        
        self._buttons = []
        for i, value in enumerate(self._values):
            color_idx = i % len(colors)
            fg_color = colors[color_idx]
            is_current = (value == self._current)
            
            btn = ctk.CTkButton(
                self._scroll_frame,
                text=value,
                command=lambda v=value: self._select_value(v),
                height=32,
                font=ctk.CTkFont(size=12),
                anchor="w",
                fg_color=("#fffacd", "gray30") if not is_current else fg_color,
                hover_color=fg_color,
                text_color=("black", "white") if not is_current else "white",
                border_color=("#87ceeb", "#5dade2"),
                border_width=2,
                corner_radius=6
            )
            btn.pack(fill="x", padx=3, pady=2)
            self._buttons.append(btn)
        
        # CRITICAL FIX: Force focus and lift after packing all widgets
        self._dropdown.update_idletasks()
        self._dropdown.lift()
        self._dropdown.focus_force()
        
        # Bind events
        self._dropdown.bind("<FocusOut>", self._on_focus_out, add="+")
        self._dropdown.bind("<Escape>", lambda e: self._close_dropdown(), add="+")
        
        # Bind click outside to close
        self._dropdown.bind("<Button-1>", self._check_click_outside, add="+")
    
    def _on_focus_out(self, event):
        """Handle focus out event"""
        # Small delay to allow button clicks to register
        self.after(100, self._close_dropdown)
    
    def _check_click_outside(self, event):
        """Check if click is outside dropdown"""
        if event.widget == self._dropdown:
            self._close_dropdown()
    
    def _close_dropdown(self):
        """Close dropdown menu"""
        if self._dropdown and self._dropdown.winfo_exists():
            self._dropdown.destroy()
        self._dropdown = None
        self._scroll_frame = None
        self._buttons = []
    
    def _select_value(self, value: str):
        """Select a value from dropdown"""
        self.set(value)
        self._close_dropdown()
    
    def _on_wheel(self, event):
        """Handle mouse wheel to cycle through values"""
        if not self._values:
            return "break"
        
        try:
            current_idx = self._values.index(self._current)
        except ValueError:
            current_idx = 0
        
        # Determine scroll direction
        delta = getattr(event, "delta", 0)
        if delta == 0 and hasattr(event, "num"):
            delta = 120 if event.num == 4 else -120
        
        # Cycle through values
        if delta > 0:
            new_idx = (current_idx - 1) % len(self._values)
        else:
            new_idx = (current_idx + 1) % len(self._values)
        
        self.set(self._values[new_idx])
        return "break"


# ==================== Modbus RTU Protocol ====================
class ModbusRTU:
    """Modbus RTU protocol implementation with CRC validation"""
    
    EX_MAP = {
        1: "Illegal Function",
        2: "Illegal Data Address",
        3: "Illegal Data Value",
        4: "Slave Device Failure",
        5: "Acknowledge",
        6: "Slave Device Busy",
        8: "Memory Parity Error",
        10: "Gateway Path Unavailable",
        11: "Gateway Target Device Failed to Respond",
    }

    @staticmethod
    def crc16(data: bytes) -> int:
        """Calculate Modbus CRC-16"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    @staticmethod
    def build_frame(slave_id: int, function: int, data: bytes) -> bytes:
        """Build Modbus frame with CRC"""
        frame = bytes([slave_id, function]) + data
        crc = ModbusRTU.crc16(frame)
        return frame + struct.pack('<H', crc)

    @staticmethod
    def read_holding_registers(slave_id: int, start_addr: int, quantity: int) -> bytes:
        """Build read holding registers request (Function 0x03)"""
        if not (1 <= slave_id <= 247):
            raise ValueError(f"Invalid slave ID: {slave_id}")
        if not (1 <= quantity <= 125):
            raise ValueError(f"Invalid quantity: {quantity}")
        data = struct.pack('>HH', start_addr, quantity)
        return ModbusRTU.build_frame(slave_id, 0x03, data)

    @staticmethod
    def write_single_register(slave_id: int, addr: int, value: int) -> bytes:
        """Build write single register request (Function 0x06)"""
        if not (1 <= slave_id <= 247):
            raise ValueError(f"Invalid slave ID: {slave_id}")
        if not (0 <= value <= 0xFFFF):
            raise ValueError(f"Invalid value: {value}")
        data = struct.pack('>HH', addr, value)
        return ModbusRTU.build_frame(slave_id, 0x06, data)

    @staticmethod
    def parse_response(response: bytes, expected_slave: int, expected_func: int) -> Tuple[bool, Any]:
        """Parse and validate Modbus response"""
        if len(response) < 5:
            return False, "Response too short"

        slave_id, func = response[0], response[1]
        if slave_id != expected_slave:
            return False, "Slave ID mismatch"

        # Verify CRC
        received_crc = struct.unpack('<H', response[-2:])[0]
        calculated_crc = ModbusRTU.crc16(response[:-2])
        if received_crc != calculated_crc:
            return False, "CRC error"

        # Check for exception
        if func & 0x80:
            if len(response) < 5:
                return False, "Exception frame too short"
            code = response[2]
            return False, ModbusRTU.EX_MAP.get(code, f"Exception 0x{code:02X}")

        if func != expected_func:
            return False, "Function mismatch"

        # Extract data based on function code
        if func == 0x03:  # Read holding registers
            byte_count = response[2]
            expected_total = 5 + byte_count
            if len(response) != expected_total:
                return False, f"Length mismatch: got {len(response)}, expected {expected_total}"
            data = response[3:-2]
            if len(data) % 2 != 0:
                return False, "Byte count not even"
            values = [struct.unpack('>H', data[i:i+2])[0] for i in range(0, len(data), 2)]
            return True, values

        if func == 0x06:  # Write single register
            if len(response) != 8:
                return False, f"Write response length mismatch: {len(response)}"
            addr, value = struct.unpack('>HH', response[2:6])
            return True, (addr, value)

        return True, response[2:-2]


# ==================== Serial Manager ====================
class SerialManager:
    """Thread-safe serial communication manager"""
    
    def __init__(self):
        self.port: Optional[serial.Serial] = None
        self.lock = threading.Lock()
        self.connected = False
        self.max_retries = 3
        self.inter_frame_delay = 0.01

    def connect(self, port_name: str, baudrate: int, bytesize: int,
                parity: str, stopbits: int, timeout: float) -> Tuple[bool, str]:
        """Connect to serial port"""
        with self.lock:
            try:
                if self.connected:
                    return False, "Already connected"

                parity_map = {'N': serial.PARITY_NONE, 'E': serial.PARITY_EVEN, 'O': serial.PARITY_ODD}
                bytesize_map = {7: serial.SEVENBITS, 8: serial.EIGHTBITS}
                stopbits_map = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}

                self.port = serial.Serial(
                    port=port_name,
                    baudrate=baudrate,
                    bytesize=bytesize_map.get(bytesize, serial.EIGHTBITS),
                    parity=parity_map.get(parity, serial.PARITY_NONE),
                    stopbits=stopbits_map.get(stopbits, serial.STOPBITS_ONE),
                    timeout=timeout,
                    write_timeout=timeout,
                )
                self.connected = True

                # Calculate inter-frame delay (3.5 character times)
                char_time = 11.0 / max(baudrate, 300)
                self.inter_frame_delay = max(3.5 * char_time, 0.00175)
                
                return True, f"Connected to {port_name}"

            except Exception as e:
                self.connected = False
                return False, f"Connection failed: {e}"

    def disconnect(self) -> Tuple[bool, str]:
        """Disconnect from serial port"""
        with self.lock:
            try:
                if self.port and self.port.is_open:
                    self.port.close()
                self.port = None
                self.connected = False
                return True, "Disconnected"
            except Exception as e:
                return False, f"Disconnect error: {e}"

    def _expected_response_length(self, func: int, buf: bytearray) -> int:
        """Calculate expected response length based on function code"""
        if func == 0x06:
            return 8
        if func == 0x03:
            if len(buf) >= 3:
                byte_count = buf[2]
                return 5 + byte_count
            return 0
        return 0

    def transact(self, request: bytes, expected_slave: int, expected_func: int,
                 timeout: float = 0.5) -> Tuple[bool, Any]:
        """Send request and receive response with retries"""
        if not self.connected or not self.port:
            return False, "Not connected"

        for attempt in range(self.max_retries):
            with self.lock:
                try:
                    # Inter-frame delay
                    time.sleep(self.inter_frame_delay)
                    
                    # Clear buffers and send
                    self.port.reset_input_buffer()
                    self.port.reset_output_buffer()
                    self.port.write(request)
                    self.port.flush()

                    # Read response with length awareness
                    start_time = time.time()
                    buffer = bytearray()
                    expected_len = 0

                    while (time.time() - start_time) < timeout:
                        chunk = self.port.read(256)
                        if chunk:
                            buffer.extend(chunk)
                            if len(buffer) >= 2:
                                expected_len = self._expected_response_length(expected_func, buffer)
                            if expected_len and len(buffer) >= expected_len:
                                break
                        else:
                            time.sleep(0.003)

                    if not buffer:
                        if attempt < self.max_retries - 1:
                            time.sleep(0.05)
                            continue
                        return False, "Timeout - No response"

                    if expected_len and len(buffer) < expected_len:
                        if attempt < self.max_retries - 1:
                            time.sleep(0.05)
                            continue
                        return False, f"Incomplete response ({len(buffer)}/{expected_len} bytes)"

                    return ModbusRTU.parse_response(bytes(buffer), expected_slave, expected_func)

                except Exception as e:
                    if attempt < self.max_retries - 1:
                        time.sleep(0.05)
                        continue
                    return False, str(e)

        return False, "Max retries exceeded"


# ==================== Main Application ====================
class ModbusControllerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Modbus RTU Controller")
        self.geometry("1400x800")

        self.serial_mgr = SerialManager()
        self.addr_definitions: List[str] = []
        self.polling = False
        self.poll_thread: Optional[threading.Thread] = None
        self.register_values = {}

        self._build_ui()
        self._auto_load_definitions()
        self._refresh_ports()

    def _build_ui(self):
        """Build the main user interface"""
        # Configure grid
        self.grid_columnconfigure(0, weight=0)  # Left panel fixed
        self.grid_columnconfigure(1, weight=1)  # Right panel expandable
        self.grid_rowconfigure(0, weight=0)     # Header
        self.grid_rowconfigure(1, weight=1)     # Content
        self.grid_rowconfigure(2, weight=0)     # Status bar

        self._build_header()
        self._build_left_panel()
        self._build_right_panel()
        self._build_status_bar()

    def _build_header(self):
        """Build application header"""
        header = ctk.CTkFrame(self, corner_radius=0, height=80, fg_color=("gray85", "gray15"))
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)

        # Title
        title = ctk.CTkLabel(
            header, 
            text="🔧 Modbus RTU Controller",
            font=ctk.CTkFont(size=32, weight="bold")
        )
        title.grid(row=0, column=0, padx=30, pady=20, sticky="w")

        # Connection status
        status_frame = ctk.CTkFrame(header, fg_color="transparent")
        status_frame.grid(row=0, column=2, padx=30, pady=20, sticky="e")
        
        self.status_dot = ctk.CTkLabel(
            status_frame,
            text="●",
            font=ctk.CTkFont(size=28),
            text_color="#ef4444"
        )
        self.status_dot.pack(side="left", padx=(0, 12))
        
        self.status_label = ctk.CTkLabel(
            status_frame,
            text="Disconnected",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.status_label.pack(side="left")

    def _build_left_panel(self):
        """Build left configuration panel"""
        left = ctk.CTkFrame(self, corner_radius=12, fg_color=("gray90", "gray17"))
        left.grid(row=1, column=0, padx=(20, 10), pady=(0, 15), sticky="nsew")
        
        # Port Configuration
        config_frame = ctk.CTkFrame(left, corner_radius=10)
        config_frame.pack(padx=20, pady=20, fill="x")
        
        ctk.CTkLabel(
            config_frame,
            text="⚙️ Port Configuration",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(padx=20, pady=(20, 15), anchor="w")

        # Configuration fields
        fields = [
            ("COM Port:", "cmb_port", [""], self._create_port_row),
            ("Baud Rate:", "cmb_baud", ['1200', '2400', '4800', '9600', '19200', '38400', '57600', '115200'], None),
            ("Data Bits:", "cmb_databits", ['7', '8'], None),
            ("Parity:", "cmb_parity", ['None (N)', 'Even (E)', 'Odd (O)'], None),
            ("Stop Bits:", "cmb_stopbits", ['1', '2'], None),
            ("Timeout (ms):", "ent_timeout", "300", None),
            ("Slave ID:", "ent_slave", "1", None),
            ("Poll Interval (ms):", "ent_poll_interval", "200", None),
        ]

        for label_text, attr_name, values_or_default, custom_func in fields:
            if custom_func:
                custom_func(config_frame, label_text, attr_name)
            elif isinstance(values_or_default, list):
                self._create_combo_row(config_frame, label_text, attr_name, values_or_default)
            else:
                self._create_entry_row(config_frame, label_text, attr_name, values_or_default)

        # Connection button
        self.btn_connection = ctk.CTkButton(
            left,
            text="📡 Connect",
            command=self._toggle_connection,
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=("#22c55e", "#16a34a"),
            hover_color=("#16a34a", "#15803d")
        )
        self.btn_connection.pack(padx=20, pady=(0, 12), fill="x")

        # Load definitions button
        ctk.CTkButton(
            left,
            text="📂 Load Address Definitions",
            command=self._load_definitions,
            height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=("#8b5cf6", "#7c3aed"),
            hover_color=("#7c3aed", "#6d28d9")
        ).pack(padx=20, pady=(0, 12), fill="x")

        # Polling button
        self.btn_polling = ctk.CTkButton(
            left,
            text="▶️ Start Polling",
            command=self._toggle_polling,
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=("#3b82f6", "#2563eb"),
            hover_color=("#2563eb", "#1d4ed8")
        )
        self.btn_polling.pack(padx=20, pady=(0, 20), fill="x")

    def _create_port_row(self, parent, label_text, attr_name):
        """Create port selection row with refresh button"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(padx=20, pady=8, fill="x")
        
        ctk.CTkLabel(
            row,
            text=label_text,
            font=ctk.CTkFont(size=13, weight="bold"),
            width=140
        ).pack(side="left", padx=(0, 10))
        
        combo = ScrollableCombo(row, values=[""], width=200)
        combo.pack(side="left", padx=(0, 8))
        setattr(self, attr_name, combo)
        
        ctk.CTkButton(
            row,
            text="🔄",
            command=self._refresh_ports,
            width=35,
            height=32,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=("#10b981", "#059669"),
            hover_color=("#059669", "#047857")
        ).pack(side="left")

    def _create_combo_row(self, parent, label_text, attr_name, values):
        """Create combobox configuration row"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(padx=20, pady=8, fill="x")
        
        ctk.CTkLabel(
            row,
            text=label_text,
            font=ctk.CTkFont(size=13, weight="bold"),
            width=140
        ).pack(side="left", padx=(0, 10))
        
        combo = ScrollableCombo(row, values=values, width=200)
        if attr_name == "cmb_baud":
            combo.set('9600')
        elif attr_name == "cmb_databits":
            combo.set('8')
        elif attr_name == "cmb_parity":
            combo.set('None (N)')
        elif attr_name == "cmb_stopbits":
            combo.set('1')
        combo.pack(side="left")
        setattr(self, attr_name, combo)

    def _create_entry_row(self, parent, label_text, attr_name, default_value):
        """Create entry field configuration row"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(padx=20, pady=8, fill="x")
        
        ctk.CTkLabel(
            row,
            text=label_text,
            font=ctk.CTkFont(size=13, weight="bold"),
            width=140
        ).pack(side="left", padx=(0, 10))
        
        entry = ctk.CTkEntry(row, width=200)
        entry.insert(0, default_value)
        entry.pack(side="left")
        setattr(self, attr_name, entry)

    def _build_right_panel(self):
        """Build right register monitoring panel"""
        right = ctk.CTkFrame(self, corner_radius=12, fg_color=("gray90", "gray17"))
        right.grid(row=1, column=1, padx=(10, 20), pady=(0, 15), sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        # Header
        header_frame = ctk.CTkFrame(right, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=25, pady=(25, 15), sticky="ew")
        header_frame.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(
            header_frame,
            text="📊 Register Monitor",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(side="left")

        # Register table
        table_frame = ctk.CTkScrollableFrame(right, corner_radius=10)
        table_frame.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="nsew")
        table_frame.grid_columnconfigure(1, weight=1)

        # Table headers
        headers = ["#", "Address", "Current Value", "Write Value (Press Enter)"]
        for col, header in enumerate(headers):
            ctk.CTkLabel(
                table_frame,
                text=header,
                font=ctk.CTkFont(size=14, weight="bold")
            ).grid(row=0, column=col, padx=15, pady=12, sticky="w")

        # Create 10 register rows
        self.reg_combos: List[ctk.CTkComboBox] = []
        self.reg_value_labels: List[ctk.CTkLabel] = []
        self.reg_write_entries: List[ctk.CTkEntry] = []

        for i in range(10):
            row = i + 1
            
            # Row number
            ctk.CTkLabel(
                table_frame,
                text=f"{i+1:02d}",
                font=ctk.CTkFont(size=13),
                width=40
            ).grid(row=row, column=0, padx=15, pady=10)

            # Address selector
            combo = ScrollableCombo(
                table_frame,
                values=["---"],
                width=350
            )
            combo.set("---")
            combo.grid(row=row, column=1, padx=15, pady=10, sticky="ew")
            self.reg_combos.append(combo)

            # Current value display
            value_label = ctk.CTkLabel(
                table_frame,
                text="----",
                font=ctk.CTkFont(size=13),
                width=120
            )
            value_label.grid(row=row, column=2, padx=15, pady=10)
            self.reg_value_labels.append(value_label)

            # Write value entry
            write_entry = ctk.CTkEntry(
                table_frame,
                placeholder_text="Enter value (0-65535)",
                width=220,
                font=ctk.CTkFont(size=12)
            )
            write_entry.grid(row=row, column=3, padx=15, pady=10, sticky="ew")
            write_entry.bind('<Return>', lambda e, idx=i: self._write_register(idx))
            self.reg_write_entries.append(write_entry)

    def _build_status_bar(self):
        """Build bottom status bar"""
        self.status_var = ctk.StringVar(value="Ready")
        status_bar = ctk.CTkFrame(self, corner_radius=0, height=40, fg_color=("gray80", "gray20"))
        status_bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        status_bar.grid_propagate(False)
        
        ctk.CTkLabel(
            status_bar,
            textvariable=self.status_var,
            font=ctk.CTkFont(size=12)
        ).pack(side="left", padx=20, pady=10)

    # ==================== Port Management ====================
    def _refresh_ports(self):
        """Refresh available COM ports"""
        try:
            ports = [p.device for p in serial.tools.list_ports.comports()]
            self.cmb_port.configure(values=ports if ports else ["No ports available"])
            if ports:
                self.cmb_port.set(ports[0])
            self._update_status("Ports refreshed")
        except Exception as e:
            self._update_status(f"Error refreshing ports: {e}")

    # ==================== Connection Management ====================
    def _toggle_connection(self):
        """Toggle serial connection"""
        if self.serial_mgr.connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        """Connect to serial port"""
        try:
            port = self.cmb_port.get()
            if not port or "No ports" in port:
                raise ValueError("Please select a valid COM port")

            baudrate = int(self.cmb_baud.get())
            bytesize = int(self.cmb_databits.get())
            parity = self.cmb_parity.get().split('(')[-1].strip(')')
            stopbits = int(self.cmb_stopbits.get())
            timeout = int(self.ent_timeout.get()) / 1000.0

            ok, msg = self.serial_mgr.connect(port, baudrate, bytesize, parity, stopbits, timeout)
            
            if ok:
                # Update UI on success
                self.after(0, lambda: self._update_connection_ui(True))
                self._update_status(f"✓ {msg} @ {baudrate} baud")
            else:
                raise Exception(msg)
                
        except Exception as e:
            self._update_status(f"✗ Connection failed: {e}")
            messagebox.showerror("Connection Error", str(e))

    def _disconnect(self):
        """Disconnect from serial port"""
        try:
            if self.polling:
                self._stop_polling()
            
            self.serial_mgr.disconnect()
            self.after(0, lambda: self._update_connection_ui(False))
            self._update_status("✓ Disconnected")
            
        except Exception as e:
            self._update_status(f"✗ Disconnect error: {e}")

    def _update_connection_ui(self, connected: bool):
        """Update UI elements based on connection status"""
        if connected:
            self.status_dot.configure(text_color="#22c55e")
            self.status_label.configure(text="Connected")
            self.btn_connection.configure(
                text="🔌 Disconnect",
                fg_color=("#ef4444", "#dc2626"),
                hover_color=("#dc2626", "#b91c1c")
            )
        else:
            self.status_dot.configure(text_color="#ef4444")
            self.status_label.configure(text="Disconnected")
            self.btn_connection.configure(
                text="📡 Connect",
                fg_color=("#22c55e", "#16a34a"),
                hover_color=("#16a34a", "#15803d")
            )

    # ==================== Address Definitions ====================
    def _auto_load_definitions(self):
        """Auto-load definitions from default path"""
        try:
            default_path = Path('./setting/address_def.ddata')
            if default_path.exists():
                self._load_definitions_file(str(default_path))
        except Exception:
            pass

    def _load_definitions(self):
        """Load address definitions from file"""
        try:
            initial_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            initial_dir = os.getcwd()

        filepath = filedialog.askopenfilename(
            title="Select Address Definition File",
            filetypes=[("Data files", "*.ddata"), ("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=initial_dir,
        )
        
        if filepath:
            self._load_definitions_file(filepath)

    def _load_definitions_file(self, filepath: str):
        """Load definitions from specified file"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]
            
            if not lines:
                raise ValueError("File is empty")

            self.addr_definitions = lines
            items = [f"{i:03d}_{name}" for i, name in enumerate(lines)]

            # Update all combo boxes
            for combo in self.reg_combos:
                combo.configure(values=items)
                if items:
                    combo.set(items[0])

            filename = Path(filepath).name
            self._update_status(f"✓ Loaded {len(lines)} addresses from {filename}")
            
        except Exception as e:
            self._update_status(f"✗ Failed to load file: {e}")
            messagebox.showerror("Error", f"Failed to load file:\n{e}")

    # ==================== Polling ====================
    def _toggle_polling(self):
        """Toggle register polling"""
        if self.polling:
            self._stop_polling()
        else:
            self._start_polling()

    def _start_polling(self):
        """Start polling registers"""
        if not self.serial_mgr.connected:
            messagebox.showwarning("Not Connected", "Please connect to a serial port first")
            return
        
        try:
            interval_ms = int(self.ent_poll_interval.get())
            if interval_ms < 50:
                raise ValueError("Poll interval must be >= 50ms")

            self.polling = True
            self.btn_polling.configure(
                text="⏸️ Stop Polling",
                fg_color=("#ef4444", "#dc2626"),
                hover_color=("#dc2626", "#b91c1c")
            )
            
            self.poll_thread = threading.Thread(target=self._polling_loop, daemon=True)
            self.poll_thread.start()
            self._update_status("✓ Polling started")
            
        except Exception as e:
            self._update_status(f"✗ Failed to start polling: {e}")
            messagebox.showerror("Error", str(e))

    def _stop_polling(self):
        """Stop polling registers"""
        self.polling = False
        self.btn_polling.configure(
            text="▶️ Start Polling",
            fg_color=("#3b82f6", "#2563eb"),
            hover_color=("#2563eb", "#1d4ed8")
        )
        self._update_status("✓ Polling stopped")

    def _polling_loop(self):
        """Main polling loop (runs in separate thread)"""
        while self.polling:
            try:
                slave_id = int(self.ent_slave.get())
                interval = int(self.ent_poll_interval.get()) / 1000.0
                timeout = int(self.ent_timeout.get()) / 1000.0

                for i, combo in enumerate(self.reg_combos):
                    if not self.polling:
                        break
                    
                    addr_str = combo.get()
                    if not addr_str or addr_str == "---":
                        continue
                    
                    try:
                        # Extract address from format "000_Name"
                        addr = int(addr_str.split('_', 1)[0])
                        
                        # Build and send read request
                        request = ModbusRTU.read_holding_registers(slave_id, addr, 1)
                        ok, result = self.serial_mgr.transact(request, slave_id, 0x03, timeout=timeout)
                        
                        if ok and isinstance(result, list) and result:
                            value = result[0]
                            self.register_values[addr] = (value, time.time())
                            # Thread-safe UI update
                            self.after(0, lambda idx=i, v=value: self._update_register_display(idx, v, None))
                        else:
                            error_msg = result if isinstance(result, str) else "Read failed"
                            self.after(0, lambda idx=i, err=error_msg: self._update_register_display(idx, None, err))
                    
                    except Exception as e:
                        self.after(0, lambda idx=i, err=str(e): self._update_register_display(idx, None, err))

                time.sleep(interval)

            except ValueError as e:
                self.after(0, lambda: self._update_status(f"✗ Invalid configuration: {e}"))
                time.sleep(1)
            except Exception as e:
                self.after(0, lambda: self._update_status(f"✗ Polling error: {e}"))
                time.sleep(1)

    def _update_register_display(self, index: int, value: Optional[int], error: Optional[str]):
        """Update register display (must be called from main thread)"""
        if value is not None:
            self.reg_value_labels[index].configure(
                text=str(value),
                text_color=("gray10", "gray90")
            )
        else:
            error_text = "ERR" if not error else ("TMOUT" if "timeout" in error.lower() else "ERR")
            self.reg_value_labels[index].configure(
                text=error_text,
                text_color="#ef4444"
            )

    # ==================== Write Register ====================
    def _write_register(self, index: int):
        """Write value to register"""
        if not self.serial_mgr.connected:
            messagebox.showwarning("Not Connected", "Please connect to a serial port first")
            return
        
        try:
            # Get configuration
            slave_id = int(self.ent_slave.get())
            timeout = int(self.ent_timeout.get()) / 1000.0
            
            # Get address
            addr_str = self.reg_combos[index].get()
            if not addr_str or addr_str == "---":
                raise ValueError("Please select an address")
            addr = int(addr_str.split('_', 1)[0])

            # Get value
            value_str = self.reg_write_entries[index].get().strip()
            if not value_str:
                raise ValueError("Please enter a value")
            value = int(value_str)
            
            if not (0 <= value <= 65535):
                raise ValueError("Value must be between 0 and 65535")

            # Build and send write request
            request = ModbusRTU.write_single_register(slave_id, addr, value)
            ok, result = self.serial_mgr.transact(request, slave_id, 0x06, timeout=timeout)
            
            if not ok:
                raise Exception(result)

            # Verify by reading back
            read_req = ModbusRTU.read_holding_registers(slave_id, addr, 1)
            ok2, result2 = self.serial_mgr.transact(read_req, slave_id, 0x03, timeout=timeout)
            
            displayed_value = value
            if ok2 and isinstance(result2, list) and result2:
                displayed_value = result2[0]

            # Update UI
            self.reg_write_entries[index].delete(0, 'end')
            self.reg_value_labels[index].configure(
                text=str(displayed_value),
                text_color=("gray10", "gray90")
            )
            self._update_status(f"✓ Write successful: Address {addr} = {displayed_value}")

        except ValueError as e:
            self._update_status(f"✗ Input error: {e}")
            messagebox.showerror("Input Error", str(e))
        except Exception as e:
            self._update_status(f"✗ Write failed: {e}")
            messagebox.showerror("Write Error", str(e))

    # ==================== Utilities ====================
    def _update_status(self, message: str):
        """Update status bar message (thread-safe)"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_var.set(f"[{timestamp}] {message}")

    def _on_closing(self):
        """Handle application closing"""
        try:
            if self.polling:
                self._stop_polling()
            if self.serial_mgr.connected:
                self.serial_mgr.disconnect()
        except Exception:
            pass
        self.destroy()


# ==================== Entry Point ====================
def main():
    """Application entry point"""
    app = ModbusControllerApp()
    app.protocol("WM_DELETE_WINDOW", app._on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()