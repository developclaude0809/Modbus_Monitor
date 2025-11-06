# 🧩 Alarm Log 定義文件
*(統一格式，適用 Alarm_01 ~ Alarm_20)*

---

## 📘 概要說明
Alarm Log 負責顯示最近 20 筆異常記錄。  
每筆 Alarm 含七個固定欄位：

```
Status, I, V, Temp, Hr, Min, Sec
```
所有 Alarm_01 ~ Alarm_20 皆採相同結構與比例設定。  
資料由 Modbus 03 指令讀取位址範圍 115~254 (0x73~0xFE)。

---

## 🗂️ `.ddata` 統一格式定義

| Title | Format | Ratio | Show | 說明 |
|:--|:--|:--:|:--|:--|
| Status | bitstatus | 1 | OV\|UV\|OC\|OT\|FAN_FAIL\|TEMP_HIGH\|COMM_ERR\|POWER_FAIL\|PHASE_LOSS\|OVERLOAD\|CURR_IMB\|VOLT_IMB\|SENSOR_ERR\|BRAKE_ERR\|EEPROM_ERR\|RESERVE | 每一 bit 對應 Alarm 狀態；多個同時亮時以逗號分隔顯示。 |
| I | value | 0.001 | uint16 | 電流值 (A)，比例 1000:1 |
| V | value | 1 | uint16 | 電壓值 (V)，比例 1:1 |
| Temp | value | 0.1 | uint16 | 溫度值 (°C)，比例 10:1 |
| Hr | value | 1 | uint16 | 累積運行時間（小時） |
| Min | value | 1 | uint16 | 累積運行時間（分鐘） |
| Sec | value | 1 | uint16 | 累積運行時間（秒） |

> UI 端自動將 Hr/Min/Sec 聚合成「Runtime = Hr:MM:SS」顯示。

---

## 📄 實際 `.ddata` 範例

```csv
# ---- Alarm ----
Status,bitstatus,1,OV|UV|OC|OT|FAN_FAIL|TEMP_HIGH|COMM_ERR|POWER_FAIL|PHASE_LOSS|OVERLOAD|CURR_IMB|VOLT_IMB|SENSOR_ERR|BRAKE_ERR|EEPROM_ERR|RESERVE
I,value,0.001,uint16
V,value,1,uint16
Temp,value,0.1,uint16
Hr,value,1,uint16
Min,value,1,uint16
Sec,value,1,uint16
```

此七行格式適用於 Alarm_01 ~ Alarm_20，全系統共用。

---

## 🖥️ UI 顯示規劃

| 區域 | 顯示內容 | 規則 |
|:--|:--|:--|
| **列表行** | 每筆 Alarm 顯示 Label 與 Data | Label 為 Alarm 序號 (01~20)，Data 為下列七項資訊。 |
| **Status** | 顯示所有 active bit 對應文字 | 例如：`OC, OT, FAN_FAIL` |
| **I / V / Temp** | 依比例換算後顯示 | 小數自動裁切；附單位 (A, V, °C)。 |
| **Runtime** | 聚合 Hr/Min/Sec | 顯示格式：`200:05:09`（Hr:MM:SS）。 |
| **Refresh** | 按鈕位於上方 | 重新讀取 Alarm Log 資料。 |
| **Last Update** | 顯示最後更新時間 | 範例：`Last update: 2025-11-06 14:32:15` |

> 不顯示 Raw/Addr/Hex 等內部欄位。  
> 視窗為 **非阻塞 (Non-Modal)**，可同時操作主畫面。

---

## ⚙️ 資料刷新與例外處理

## ⚙️ 資料刷新與例外處理

- **Refresh 按鈕** 重新讀取位址 `115~254`。  
- **通訊採非同步背景執行**，不阻塞主 UI。  
- **每筆 Alarm 需一次連續讀取 7 筆暫存器**，例如：  
  - Alarm_01 → `115~121`  
  - Alarm_02 → `122~128`
- 若讀取失敗，會進行retry(至多3次)  
- **缺值顯示** `—`，非法值 (`Min ≥ 60` 或 `Sec ≥ 60`) 以紅字顯示並加 tooltip 提示。  
- **Status = 0** → 顯示 `Normal`。  
- **未命名 bit** → 跳過不顯示。
 

---

## 💡 設計摘要

1. **非阻塞顯示設計**：視窗為 Non-Modal，可與主畫面同時操作。  
2. **統一定義**：所有 20 筆 Alarm 使用相同 `.ddata` 結構。  
3. **資料聚合**：時間欄位自動合併成 Runtime。  
4. **動態狀態呈現**：bitstatus 支援多狀態同時顯示。  
5. **即時刷新**：提供手動 Refresh 按鈕與更新時間顯示。  
6. **資料格式匯入**:在Load Setting功能加入Alarm log的資訊

---
