# 本機參考沙盒

本目錄是可獨立執行的最小參考服務，從 Cross 的設備沙盒明確列出的檔案產生。只有 FastAPI、Pydantic、Uvicorn 與 SQLite，未包含正式預約程式、環境設定或私有資料。Python 3.14 已驗證。

從文件包根目錄啟動：

```sh
python -m pip install -r examples/local-sandbox/requirements.txt
# 先設定自己的 CROSS_SANDBOX_TOKEN，至少 32 個可見 ASCII 字元
python -m uvicorn sandbox.api:app_factory --factory \
  --app-dir examples/local-sandbox --host 127.0.0.1 --port 8002
```

詳細操作見 [快速開始](../../docs/quickstart.md)。停止服務後資料庫仍保留；`scripts/verify.py` 的暫存資料庫會在驗證結束後清除。

`sandbox/test_api.py` 保留來源的 API 測試。額外安裝 pytest 與 httpx 後，可在本目錄執行 `python -m pytest sandbox/test_api.py -q`；範例包的 `scripts/verify.py` 不需要這兩個套件。

本服務只有單一 bearer 身份，沒有多租戶或正式設備授權。只接收合成 ECG 與虛構心率；不作正式後端、FHIR server 或醫療診斷用途。
