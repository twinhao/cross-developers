"""啟動獨立範例服務，以實際 HTTP 驗證兩種客戶端與錯誤處理。"""

import copy
import hashlib
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with TemporaryDirectory(prefix="cross-public-kit-") as directory:
        token = secrets.token_urlsafe(32)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        environment = os.environ | {
            "CROSS_SANDBOX_TOKEN": token,
            "CROSS_SANDBOX_DB": str(Path(directory) / "data.sqlite3"),
            "CROSS_SANDBOX_URL": base,
            "PYTHONPATH": str(ROOT / "examples/local-sandbox"),
        }
        with (Path(directory) / "server.log").open("w+") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "sandbox.api:app_factory",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        with urlopen(base + "/openapi.json", timeout=1) as response:
                            live_schema = json.load(response)
                        break
                    except URLError, TimeoutError:
                        if server.poll() is not None or time.monotonic() >= deadline:
                            log.seek(0)
                            raise RuntimeError(
                                "本機範例服務無法啟動：" + log.read()[-2000:]
                            ) from None
                        time.sleep(0.1)
                expected_schema = json.loads(
                    (ROOT / "openapi/cross-sandbox.openapi.json").read_text()
                )
                if live_schema != expected_schema:
                    raise RuntimeError("OpenAPI 文件與範例服務不一致")
                for kind in ("heart-rate", "ecg"):
                    subprocess.run(
                        [
                            sys.executable,
                            str(ROOT / "examples/python/upload.py"),
                            "--kind",
                            kind,
                        ],
                        env=environment,
                        check=True,
                        timeout=30,
                    )
                node = shutil.which("node")
                if node:
                    for kind in ("heart-rate", "ecg"):
                        subprocess.run(
                            [node, str(ROOT / "examples/javascript/upload.mjs"), kind],
                            env=environment,
                            check=True,
                            timeout=30,
                        )
                else:
                    print("未安裝 Node，JavaScript 範例未驗證；請安裝後再執行。")

                def request(
                    path: str, data: dict[str, Any] | None = None, auth: str = token
                ) -> tuple[int, dict[str, Any]]:
                    body = None if data is None else json.dumps(data).encode()
                    request = Request(
                        base + path,
                        data=body,
                        headers={
                            "Authorization": f"Bearer {auth}",
                            "Content-Type": "application/json",
                        },
                    )
                    try:
                        with urlopen(request, timeout=5) as response:
                            return response.status, json.load(response)
                    except HTTPError as error:
                        return error.code, json.load(error)

                payload = json.loads((ROOT / "fixtures/ecg.json").read_text())
                path = "/api/v1/measurements/ecg"
                status, receipt = request(path, payload)
                if status != 200 or receipt["duplicate"] is not True:
                    raise RuntimeError("兩種客戶端重送的事件應保持同一筆紀錄")
                if request(path, payload, "invalid-demo-token")[0] != 401:
                    raise RuntimeError("錯誤授權碼應拒絕")
                corrupt = copy.deepcopy(payload)
                corrupt["waveform"]["samples"][0] += 1
                if request(path, corrupt)[0] != 422:
                    raise RuntimeError("校驗碼不符應拒絕")
                samples = corrupt["waveform"]["samples"]
                corrupt["waveform"]["sample_sha256"] = hashlib.sha256(
                    struct.pack(f"<{len(samples)}i", *samples)
                ).hexdigest()
                if request(path, corrupt)[0] != 409:
                    raise RuntimeError("校驗有效但改變原事件內容應回衝突")
                if (
                    request(
                        f"/api/v1/measurements/{receipt['measurement']['id']}/export/fhir"
                    )[0]
                    != 501
                ):
                    raise RuntimeError("ECG 未驗證的 FHIR 匯出應明確拒絕")
                print("OpenAPI 一致、授權拒絕、損壞樣本、事件衝突及 ECG 匯出限制：通過")
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    main()
