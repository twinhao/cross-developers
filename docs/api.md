# API 契約：Developer Preview 0.3.0

請求與回應的機器可讀定義見 [OpenAPI](../openapi/cross-sandbox.openapi.json)。本版使用 Cross 原生 JSON，`schema_version=1.0`；API 實作版本與資料封套版本是兩個不同值。

本機基底網址 `http://127.0.0.1:8002`。所有 `/api/v1/` 路徑需要 `Authorization: Bearer <沙盒授權碼>`。授權碼由服務操作者設定，沒有發碼、帳號登入、refresh 或租戶隔離 API。`/docs` 與 `/openapi.json` 提供本機文件。

## 介面

| 方法與路徑 | 用途 | 成功回應 |
|---|---|---|
| POST /api/v1/patients | 登錄虛構病人來源 | 201 新建／200 相同登錄，病人 JSON |
| GET /api/v1/patients/{id} | 查詢登錄病人 | 200，病人 JSON |
| POST /api/v1/devices | 登錄設備及來源 | 201 新建／200 相同登錄，設備 JSON |
| GET /api/v1/devices/{id} | 查詢登錄設備 | 200，設備 JSON |
| POST /api/v1/measurements/heart-rate | 接收單筆心率 | 201 新建／200 重送，接收回執 |
| POST /api/v1/measurements/ecg | 接收完整合成 ECG | 201 新建／200 重送，接收回執 |
| GET /api/v1/measurements/{id} | 讀回原生紀錄 | 200，量測 JSON |
| GET /api/v1/measurements/{id}/export/fhir | 選用的心率轉換範例 | 心率 200；ECG 501 |

沒有清單、修改、刪除、訂閱 Webhook 或 FHIR Patient／Device 介面。本版不接受未知欄位；識別碼與數值限制以 OpenAPI 為準。

## 登錄與來源識別

先登錄病人與設備，再傳量測。參考 [patient.json](../fixtures/patient.json)、[device.json](../fixtures/device.json)。

- 病人／設備 id 須符合 `demo-` 識別碼格式；此約定不是去識別化措施。
- `source_system + external_id` 在各類登錄資料中唯一。不同廠商／機構需使用不同來源命名空間。
- 設備保存 `manufacturer`、`model`、`firmware_version`。
- 相同 id、相同完整內容再次登錄回 200；更改內容或重複來源識別會回 409。本版登錄資料不可更新。
- 正式病人身份解析、租戶、設備與病人配對是後續設計，不由 demo- id 提供授權。

## 心率

```json
{
  "schema_version": "1.0",
  "event_id": "demo-measurement-001",
  "patient_id": "demo-patient-001",
  "device_id": "demo-device-001",
  "measured_at": "2026-10-06T10:00:00+08:00",
  "heart_rate": 72,
  "unit": "/min"
}
```

0 < heart_rate ≤ 400，單位固定 `/min`。這是沙盒輸入限制，不是正常值判定。schema_version 與單位省略時使用上述預設；範例客戶端會核對回應的實際值。

## 接收回執與讀回

成功回執包含 `duplicate` 與 `measurement`。量測包含原事件、伺服器 `id`、`kind`、`received_at`，以及登錄時的病人與設備來源快照；ECG 另有樣本數與時間長度。

`event_id` 是來源事件識別；`measurement.id` 是 Cross 紀錄識別。查詢路徑使用後者。

收到回執後再 GET 讀回，核對身份、時間、單位與完整資料。範例客戶端核對完整來源快照及波形，不因只有成功狀態碼就宣稱同步完成。FHIR 匯出不是一般接收／讀回流程的一部分。

## 去重與時間

去重範圍為 **device_id + event_id**。首次接收回 201／duplicate=false；原樣重送回 200／duplicate=true，保留同一伺服器 id。相同識別改變內容回 409，心率與 ECG 共用此去重範圍。

量測時間必須含時區，後端正規化 UTC。原生時間保存到微秒；範例只使用最多 6 位小數。相同瞬間的不同時區表達可以重送。量測時間與接收時間分開，離線補傳不得將 measured_at 改為當下時間。

## 錯誤與處理

錯誤 JSON 使用 `detail`：業務錯誤通常是文字，欄位驗證錯誤是陣列。OpenAPI 以兩種形狀描述；這不是 FHIR OperationOutcome。

| 狀態 | 原因／客戶端行為 |
|---|---|
| 401 | 無有效身份；保留原事件，取得有效授權後重試 |
| 404 | 查無紀錄或參照；核對使用的是伺服器 id 與同一沙盒 |
| 409 | 登錄或事件內容衝突；保留原始資料供處理，不能換 event_id 繞過 |
| 422 | 欄位格式、校驗碼、版本或參照登錄不符；先修正流程 |
| 501 | ECG 的 FHIR 映射尚未驗證；改用原生查詢 |
| 408／429／5xx／連線失敗 | 客戶端應保留原事件並作有限度退避重試；沙盒沒有額外提供配額或背景排程能力 |

逾時時服務可能已保存。重試必須使用同一事件與內容；收到無法核對的回執或讀回失敗也不能丟棄事件。範例客戶端只演示一次原樣重送，沒有自動背景重試。

## 相容性範圍

本機資料與程式用來驗證廠商接入方式，不代表正式服務 SLA、臨床效能或負載容量。心率的選用 FHIR 範例不宣告 TW Core／健保相容性通過，也不是完整可解析的 FHIR 資料集。接收方規格確定後才建立正式交換 adapter。
