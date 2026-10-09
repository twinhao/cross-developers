"""只使用標準函式庫的本機合成資料串接範例，非正式 SDK。"""

import argparse
import hashlib
import json
import os
import struct
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: Any, msg: Any, headers: Any, newurl: Any
    ) -> None:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("heart-rate", "ecg"), default="ecg")
    args = parser.parse_args()
    base = os.environ.get("CROSS_SANDBOX_URL", "http://127.0.0.1:8002").rstrip("/")
    url = urlparse(base)
    if (
        url.scheme != "http"
        or url.hostname not in ("127.0.0.1", "localhost")
        or url.username
        or url.password
        or url.path
        or url.query
        or url.fragment
    ):
        raise ValueError("此範例僅支援 http 的本機 loopback 沙盒 URL")
    token = os.environ.get("CROSS_SANDBOX_TOKEN", "")
    if len(token) < 32 or not all(33 <= ord(char) <= 126 for char in token):
        raise ValueError("請在環境變數設定至少 32 個可見 ASCII 字元的沙盒授權碼")
    opener = build_opener(NoRedirect(), ProxyHandler({}))

    def load(name: str) -> dict[str, Any]:
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("樣本需為 JSON 物件")
        return data

    def send(
        method: str, path: str, data: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode()
        request = Request(
            base + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            raise RuntimeError(
                f"HTTP {error.code}：請依文件處理，保留原事件，不更換 event_id"
            ) from None

    patient, device = load("patient.json"), load("device.json")
    for path, data in (("patients", patient), ("devices", device)):
        status, registered = send("POST", f"/api/v1/{path}", data)
        if status not in (200, 201) or registered != data:
            raise RuntimeError("登錄回應無法確認")
    payload = load(args.kind + ".json")
    if args.kind == "ecg":
        waveform = payload["waveform"]
        samples = waveform["samples"]
        if not all(
            type(value) is int and -100000 <= value <= 100000 for value in samples
        ):
            raise ValueError("樣本需為契約範圍內的有號整數 µV")
        checksum = hashlib.sha256(
            struct.pack(f"<{len(samples)}i", *samples)
        ).hexdigest()
        if checksum != waveform["sample_sha256"]:
            raise ValueError("本機樣本校驗碼不符")
    status, first = send("POST", f"/api/v1/measurements/{args.kind}", payload)
    if status not in (200, 201) or first["duplicate"] is not (status == 200):
        raise RuntimeError("接收狀態無法確認")
    status, retry = send("POST", f"/api/v1/measurements/{args.kind}", payload)
    if (
        status != 200
        or retry["duplicate"] is not True
        or retry["measurement"] != first["measurement"]
    ):
        raise RuntimeError("原樣重送未去重或回執不一致")
    record = first["measurement"]
    if not isinstance(record.get("id"), str) or not record["id"]:
        raise RuntimeError("回執缺少伺服器 id")
    for key in ("event_id", "patient_id", "device_id"):
        if record[key] != payload[key]:
            raise RuntimeError(f"回執 {key} 不一致")
    if datetime.fromisoformat(record["measured_at"]) != datetime.fromisoformat(
        payload["measured_at"]
    ):
        raise RuntimeError("回執量測時間不一致")
    if (
        record["schema_version"] != "1.0"
        or record["patient"] != patient
        or record["device"] != device
    ):
        raise RuntimeError("契約版本或來源快照不一致")
    if args.kind == "ecg":
        if (
            record["kind"] != "ecg"
            or record["unit"] != "uV"
            or record["waveform"] != payload["waveform"]
        ):
            raise RuntimeError("回執波形不一致")
        if (
            record["sample_count"] != len(samples)
            or record["duration_ms"] != len(samples) * 1000 / waveform["sample_rate_hz"]
        ):
            raise RuntimeError("回執樣本數或時間長度不一致")
    elif (
        record["kind"] != "heart_rate"
        or record["unit"] != "/min"
        or record["heart_rate"] != payload["heart_rate"]
    ):
        raise RuntimeError("回執心率不一致")
    status, stored = send("GET", f"/api/v1/measurements/{record['id']}")
    if status != 200 or stored != record:
        raise RuntimeError("讀回資料不一致；保留原事件待處理")
    print(f"{args.kind}：登錄、上傳、原樣重送去重、原生讀回核對完成")
    print(f"event_id={payload['event_id']}，伺服器 id={record['id']}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        raise SystemExit(f"串接未完成：{error}") from None
