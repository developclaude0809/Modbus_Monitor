# Modbus 0x03 / 0x04 回覆長度預估機制

## 背景
Modbus 功能碼 0x03 (Read Holding Registers) 與 0x04 (Read Input Registers) 的請求中，
已包含「讀取暫存器數量 (Quantity of Registers)」，因此可以在發送指令前預測回覆的資料長度。

## 計算公式
```
expected_len = 5 + (qty * 2)
```
- 1 byte: Slave Address  
- 1 byte: Function Code  
- 1 byte: Byte Count  
- N bytes: Data (每個暫存器 2 bytes)  
- 2 bytes: CRC

## 實作要點
1. 在送出請求時，即以 `qty` 推算 `expected_len`。  
2. 收到回覆後，再根據回覆的 Byte Count cross-check，若不一致則視為通訊錯誤。  
3. Exception Response 固定長度 5 bytes。

## 優點
- 減少等待時間與輪詢延遲  
- 提前預知應收封包長度，效率更高  
- 可立即偵測回覆異常，提升通訊穩定性  
