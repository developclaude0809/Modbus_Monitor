
# 🧱 V1 架構五步驟（專注於 View 與 Logic 的乾淨拆分）

這份文件專門針對 **V1**（不含 V2、不含 Layout 切換），  
把 UI 與邏輯分離的完整 5 步驟重新整理成 **真正工程上可執行的節奏**。

---

# 🎯 最終目標（以 V1 為核心）

1. UI（view）與邏輯（logic）分開  
2. app.py 不再塞滿 UI code  
3. logic.py 專心做 Serial / Modbus / 計算  
4. view.py 專心建構 UI 控件  
5. app.py（MainWindow）暫時充當 Controller  
6. 按鈕 UI 設定與按鈕功能邏輯完全分離

---

# 🪜 Step 1 — 把通訊邏輯搬到 `logic.py`（不碰 UI）

這一步風險最低，也對 UI 無影響。

| 項目 | 原本在 app.py | 拆到 logic.py |
|------|---------------|----------------|
| `serial.Serial(...)` 連線 | 是 | ✔ |
| `write()` / `read()` | 是 | ✔ |
| CRC 計算 | 是 | ✔ |
| 封包組裝（motor、03/04…） | 是 | ✔ |
| Background thread 讀資料 | 是 | ✔ |

建立 `SerialManager`：

```python
class SerialManager(QtCore.QObject):
    def connect_port(...):
        ...
    def send_motor_command(...):
        ...
    def read_registers_03(...):
        ...
```

app.py（MainWindow）內的功能 handler 改用 SerialManager：

```python
self.serial_mgr = SerialManager(self)

def handle_connection(self):
    ok, msg = self.serial_mgr.connect_port(...)
```

📌 **按鈕 UI 不動 → 只是改按下按鈕後的「功能」到 logic.py**

---

# 🪜 Step 2 — 把 UI 佈局拉出成 `view_v1.py`（View 層）

新建檔案：`view_v1.py`

```python
class MainView(QtCore.QObject):
    def setup_ui(self, window):
        root = QWidget()
        layout = QVBoxLayout(root)

        self.btnConnect = QPushButton("Connect")
        self.cmbPort = QComboBox()

        layout.addWidget(self.cmbPort)
        layout.addWidget(self.btnConnect)

        window.setCentralWidget(root)
```

**UI 設定（按鈕、文字、大小、佈局） → 全部搬到 View 層**

---

# 🪜 Step 3 — app.py 改成使用 View，但保留舊程式碼（re-export 技巧）

在 app.py：

```python
import view_v1

class MainWindow(QMainWindow):
    def __init__(...):
        self.ui = view_v1.MainView(self.tokens)
        self.ui.setup_ui(self)
```

### 🔁 暫時 re-export，讓舊程式碼不用一次重寫

```python
self.cmbPort = self.ui.cmbPort
self.btnConnect = self.ui.btnConnect
self.txtLog = self.ui.txtLog
```

這樣舊程式仍可用：

```python
self.btnConnect.clicked.connect(self.handle_connection)
```

**你可以慢慢改成 self.ui.xxx，而不是一次改爆全檔案。**

---

# 🪜 Step 4 — Panel 化（讓 V1 UI 模組化）

把 UI 區塊拆成檔案，例如：

```
uart_panel.py
motor_panel.py
log_panel.py
```

每個 Panel 都是 QGroupBox：

```python
class UARTPanel(QGroupBox):
    sig_connect_clicked = pyqtSignal()

    def __init__(self, tokens):
        super().__init__("UART")
        ...
```

MainView 改成：

```python
self.uart_panel = UARTPanel(self.tokens)
self.motor_panel = MotorPanel(self.tokens)
self.log_panel = LogPanel()
layout.addWidget(self.uart_panel)
layout.addWidget(self.motor_panel)
layout.addWidget(self.log_panel)
```

這樣：

- UI 更好維護  
- 每個 Panel 可以獨立重構  
- Controller 更容易接事件  

---

# 🪜 Step 5 — UI/Logic 完全分離（signal → controller → logic）

現在使用 **語意化事件** 取代 `.clicked.connect(handle_xxx)`：

### View（UI 層）

```python
self.btnConnect.clicked.connect(self.sig_connect_clicked.emit)
```

### app.py（Controller 層）

```python
self.ui.sig_connect_clicked.connect(self.handle_connection)
```

### logic.py（真正做事）

```python
self.serial_mgr.connect_port(...)
```

🔍 **這就是 MVC / MVP / MVVM 的完整架構，但保持簡單易懂。**

---

# 🎉 最終成果（只看 V1）

1. **UI 設定** → `view_v1.py` / Panel  
2. **邏輯實作** → `logic.py`  
3. **控制流程** → app.py（MainWindow）  
4. **UI 控件不再散落在 app.py**  
5. **邏輯不再和 UI 混在一起**  
6. UI 可自由改版（甚至未來新增 V2）都不會影響 logic.py

---

# 📌 在這五步裡，按鈕的「UI」與「功能」分別在哪一步做？

| 內容 | 步驟 | 檔案 | 說明 |
|------|------|--------|--------|
| 按鈕 UI（建立、文字、大小、加入 layout） | Step 2 | view_v1.py | UI 設定全移到 View |
| 按鈕功能邏輯（按下後要做什麼） | Step 1 | logic.py | connect/send/03/04… |
| 按鈕事件接線 | Step 3 | app.py | UI → Controller |
| 語意化 signal（UI 發 event） | Step 5 | view_v1.py | 避免 UI 直連邏輯 |

**這是最乾淨、最高可維護度的拆分方式。**

---
