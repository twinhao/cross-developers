# 快速開始

此流程只使用本包的合成資料，在本機完成「登錄 → 上傳 → 原樣重送 → 讀回核對」。不需要設備或 Cross 預約帳號。

## 1. 安裝本機範例服務

準備 Python 3.14。以下命令皆在 `cross-developers` 根目錄執行；兩個終端均需進入相同目錄。

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r examples/local-sandbox/requirements.txt
```

Windows 使用 `.venv\Scripts\Activate.ps1` 啟用環境，並依自己的 shell 設定下列環境變數。

## 2. 啟動沙盒

第一個終端：

```sh
export CROSS_SANDBOX_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export CROSS_SANDBOX_DB=/tmp/cross-developers-demo.sqlite3
python -m uvicorn sandbox.api:app_factory --factory \
  --app-dir examples/local-sandbox --host 127.0.0.1 --port 8002
```

開啟 [本機互動文件](http://127.0.0.1:8002/docs)，按 Authorize，輸入第一個終端的授權碼。只在本機使用；不要將 token 放入文件、範例原始碼或版本控制。

## 3. 執行獨立客戶端

第二個終端也啟用相同 Python 環境，將 `CROSS_SANDBOX_TOKEN` 設為第一個終端的相同值。可在自己的第一個終端查看變數，再貼到第二個終端；不要將內容貼進公開回報。

```sh
export CROSS_SANDBOX_TOKEN='貼上第一個終端的沙盒授權碼'
export CROSS_SANDBOX_URL=http://127.0.0.1:8002

python examples/python/upload.py --kind ecg
python examples/python/upload.py --kind heart-rate
```

Node.js 22 的 JavaScript 範例不需要 npm 套件：

```sh
node examples/javascript/upload.mjs ecg
node examples/javascript/upload.mjs heart-rate
```

成功時會顯示「登錄、上傳、原樣重送去重、原生讀回核對完成」。相同範例重跑會沿用固定 event_id，回傳同一筆伺服器紀錄；這是刻意示範重送去重。

範例客戶端限定本機 loopback，禁止重導向，不記錄 token。失敗會退出，不會換 event_id 或修改量測內容來繞過錯誤；它沒有實作正式 SDK 的離線加密或背景重試。

## 用 curl 看清楚請求

先登錄參照，再接收波形：

```sh
curl --fail-with-body http://127.0.0.1:8002/api/v1/patients \
  -H "Authorization: Bearer $CROSS_SANDBOX_TOKEN" -H 'Content-Type: application/json' \
  --data-binary @fixtures/patient.json

curl --fail-with-body http://127.0.0.1:8002/api/v1/devices \
  -H "Authorization: Bearer $CROSS_SANDBOX_TOKEN" -H 'Content-Type: application/json' \
  --data-binary @fixtures/device.json

curl --fail-with-body http://127.0.0.1:8002/api/v1/measurements/ecg \
  -H "Authorization: Bearer $CROSS_SANDBOX_TOKEN" -H 'Content-Type: application/json' \
  --data-binary @fixtures/ecg.json
```

保留回傳的 `measurement.id`，再查詢 `/api/v1/measurements/{id}`。不要將 `event_id` 誤當伺服器紀錄 id。

## 環境問題

| 情況 | 處理 |
|---|---|
| 8002 埠已使用 | 停止自己的舊沙盒，或改埠並同步 CROSS_SANDBOX_URL |
| `401` | 確認兩個終端使用同一個授權碼 |
| `409` | 檢查是否改過同一登錄資料或相同事件內容；保留原事件 |
| `422` | 檢查格式、校驗碼與病人／設備是否先登錄 |
| 本機資料庫有其他測試的同名資料 | 使用新的 CROSS_SANDBOX_DB 路徑，不刪除未知用途的資料庫 |

沙盒預設資料庫 `/tmp/cross-sandbox.sqlite3`；上例另指定範例檔。這是暫存測試方案，不能代替正式資料保存。Windows 請指定存在且可寫入的本機路徑。
