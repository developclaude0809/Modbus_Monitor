# 自動錯誤紀錄機制：Modbus_err.ddata

## 機制說明
當通訊發生異常（如超時、長度不足、CRC 錯誤、例外回覆、解析錯誤），
系統會自動將紀錄寫入 `Modbus_err.ddata` 檔案。

## 格式設計
採用 NDJSON (newline-delimited JSON) 格式，每行一筆記錄：
```json
{"ts":"2025-10-27 14:05:12","port":"COM6","baudrate":115200,"stage":"incomplete_response",
 "attempt":2,"expected_slave":1,"expected_func":3,"request_hex":"01 03 00 10 00 02 85 C9",
 "response_hex":"01 03 02 00","error":"Incomplete response (4/9)"}
```

## 記錄欄位
- ts：時間戳記  
- port / baudrate：連線資訊  
- stage：錯誤階段（timeout、parse_error、incomplete_response 等）  
- attempt：重試次數  
- expected_slave / expected_func：通訊目標  
- request_hex / response_hex：十六進制資料內容  
- error：詳細錯誤說明  

## 檔案維護
- 超過 2 MB 自動切換新檔（依時間戳命名）  
- 多執行緒寫入時採 Mutex 鎖確保安全  
- 寫檔錯誤不影響主要通訊流程  

## 優點
- 即時追蹤與重現通訊錯誤  
- 與主程式分離，不干擾運作  
- 可用 JSON 工具快速過濾與分析  
