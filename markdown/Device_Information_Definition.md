# 🧩 風機裝置資訊定義文件  
*(Version Code + Device Information)*

---

## 📘 概要說明
此區負責顯示風機裝置的版本資訊與運作參數。  
主要包含兩個資料來源區段：

1. **Firmware Version Code (Addr 0x13~0x17)** — 顯示完整韌體版本號。  
2. **Device Information (Addr 0x18~0x22)** — 顯示風機運作參數與保護設定。

所有資料皆透過 **Modbus 03 指令** 讀取，並以**非阻塞 (Non-Modal)** 視窗顯示於主介面中。

---

## 🪟 視窗行為與操作特性

| 項目 | 說明 |
|:--|:--|
| **開啟方式** | 點擊主畫面的「Device Information」按鈕。 |
| **顯示形式** | 彈出對話視窗 (Dialog)。 |
| **視窗型態** | **非阻塞 (Non-Modal)** — 開啟期間可繼續操作主視窗。 |
| **資料刷新** | 提供 **Refresh 按鈕**，按下後重新讀取所有相關暫存器。 |
| **更新方式** | 通訊採非同步執行，不阻塞主執行緒。 |
| **關閉行為** | 可自由關閉，關閉即釋放記憶體 (DeleteOnClose)。 |

---

## 🧩 Firmware Version Code (Addr 19~23)

| 名稱 | 位址(Dec) | 位址(Hex) | 說明 |
|:--|:--:|:--:|:--|
| e_03FW_M_Version1 | 19 | 0x13 | 韌體版本碼第 1 組字元（2 ASCII） |
| e_03FW_M_Version2 | 20 | 0x14 | 韌體版本碼第 2 組字元（2 ASCII） |
| e_03FW_M_Version3 | 21 | 0x15 | 韌體版本碼第 3 組字元（2 ASCII） |
| e_03FW_M_Version4 | 22 | 0x16 | 韌體版本碼第 4 組字元（2 ASCII） |
| e_03FW_M_Version5 | 23 | 0x17 | 韌體版本碼第 5 組字元（2 ASCII） |

### 🔤 顯示格式
- 每一筆暫存器儲存兩個 ASCII 字元（高位在前）。  
- 共 5 筆資料 → 10 字元。  
- 顯示時插入連字號（`-`）形成格式：  
  ```
  [FW Version] : ABCD-1234-22
  ```
- 範例：
  ```
  0x13 → 0x4142 → AB
  0x14 → 0x4344 → CD
  0x15 → 0x3132 → 12
  0x16 → 0x3334 → 34
  0x17 → 0x3232 → 22
  最終顯示：ABCD-1234-22
  ```

### 🖥️ 顯示規劃
- 顯示於視窗頂部一行。  
- 格式範例：  
  **Firmware Version : ABCD-1234-22**

---

## ⚙️ Device Information 定義區 (Addr 24~34)

| 名稱 | Label | 位址(Dec) | 位址(Hex) | 說明 | 比例 | 單位 |
|:--|:--|:--:|:--:|:--|:--:|:--:|
| e_03Fan_Speed_Max | Speed Max | 24 | 0x18 | 風扇最高轉速設定或回報值 | 1:1 | RPM |
| e_03Fan_Speed_Min | Speed Min | 25 | 0x19 | 風扇最低轉速設定或回報值 | 1:1 | RPM |
| e_03Fan_Speed_STOP | Speed Stop | 26 | 0x1A | 風扇停止門檻設定 | 1:1 | RPM |
| e_03Fan_Duty_Max | Duty Max | 27 | 0x1B | 最大占空比設定 | **10:1** | % |
| e_03Fan_Duty_Min | Duty Min | 28 | 0x1C | 最小占空比設定 | **10:1** | % |
| e_03Fan_Power_OP | Power OP | 29 | 0x1D | 風扇輸出功率（運轉功率） | 1:1 | W |
| e_03Fan_OC | OC | 30 | 0x1E | 過電流門檻/狀態 | **1000:1** | A |
| e_03Fan_OV | OV | 31 | 0x1F | 過電壓門檻/狀態 | 1:1 | V |
| e_03Fan_UV | UV | 32 | 0x20 | 欠電壓門檻/狀態 | 1:1 | V |
| e_03Fan_SV | SV | 33 | 0x21 | **未使用，不顯示** | — | — |
| e_03Fan_OT | OT | 34 | 0x22 | 過溫門檻/狀態 | **10:1** | °C |

---

## 🧱 Layout 顯示規則

| 元件 | 顯示內容 | 說明 |
|:--|:--|:--|
| **上方 (Header)** | `Firmware Version : ABCD-1234-22` | 以組合後版本字串格式顯示。 |
| **下方 (Data Table)** | 只顯示兩欄：**Label** 與 **Data** | Data 依比例換算後顯示實際值。 |
| **Label 欄** | Speed Max、Duty Max、OC、OV… | 對應各欄位名稱。 |
| **Data 欄** | 由通訊回傳的換算值 (scaled value) | 顯示即時讀值，含單位。 |
| **Refresh 按鈕** | 位於表格上方 | 重新讀取 24~34 位址。 |
| **Last Update** | 顯示最後更新時間 | 例如：`Last update: 2025-11-05 14:30:22` |

> 🔸 不顯示 Raw/Addr/Hex 等內部欄位。  
> 🔸 視窗開啟期間仍可操作主畫面。  
> 🔸 視窗關閉即釋放，不保留多實例。

---

## 💡 設計摘要
- **非阻塞顯示**：使用 `Non-Modal Dialog`，主介面可同時操作。  
- **可重整資料**：Refresh 按鈕重新請求通訊。  
- **顯示簡潔**：僅顯示 Label 與 Data。  
- **版本整合**：Version Code 以標準化格式顯示於頂部。  
- **更新提示**：顯示最後刷新時間。  
