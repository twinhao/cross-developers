"""Cross 原生設備資料沙盒；獨立於正式預約服務。"""

import hmac
import json
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sandbox.fhir import observation
from sandbox.models import (
    Device,
    EcgMeasurement,
    EcgRecord,
    IngestReceipt,
    Measurement,
    MeasurementRecord,
    Patient,
    Record,
    SandboxError,
)
from sandbox.store import Store


def create_app(db_path: Path, token: str) -> FastAPI:
    if len(token) < 32 or not token.isascii():
        raise ValueError("沙盒 token 至少需要 32 個 ASCII 字元")
    store = Store(db_path)
    app = FastAPI(
        title="Cross 本機設備沙盒",
        version="0.3.1",
        description="Cross 原生設備資料的本機合成資料範例，只有單一沙盒身份；不是正式服務或完整 FHIR server。",
        servers=[{"url": "http://127.0.0.1:8002", "description": "本機虛構資料沙盒"}],
    )
    errors: dict[int | str, dict[str, Any]] = {
        401: {"model": SandboxError, "description": "需要有效沙盒授權碼"},
        409: {"model": SandboxError, "description": "識別碼或原事件內容衝突"},
        422: {"model": SandboxError, "description": "輸入格式錯誤或參照未登錄"},
    }
    read_errors: dict[int | str, dict[str, Any]] = {
        401: errors[401],
        404: {"model": SandboxError, "description": "查無登錄資料或量測"},
    }
    bearer = HTTPBearer(auto_error=False)

    def authorize(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        if credentials is None or not hmac.compare_digest(
            credentials.credentials.encode(), token.encode()
        ):
            raise HTTPException(
                401, "需要有效的沙盒 token", headers={"WWW-Authenticate": "Bearer"}
            )

    @app.post(
        "/api/v1/patients",
        dependencies=[Depends(authorize)],
        response_model=Patient,
        responses=errors | {201: {"model": Patient, "description": "首次登錄病人"}},
        tags=["登錄"],
    )
    def register_patient(data: Patient, response: Response) -> Patient:
        response.status_code = 201 if store.register(data, "patients") else 200
        return data

    @app.post(
        "/api/v1/devices",
        dependencies=[Depends(authorize)],
        response_model=Device,
        responses=errors | {201: {"model": Device, "description": "首次登錄設備"}},
        tags=["登錄"],
    )
    def register_device(data: Device, response: Response) -> Device:
        response.status_code = 201 if store.register(data, "devices") else 200
        return data

    @app.get(
        "/api/v1/patients/{entity_id}",
        dependencies=[Depends(authorize)],
        response_model=Patient,
        responses=read_errors,
        tags=["登錄"],
    )
    def read_patient(entity_id: str) -> Patient | Device:
        return store.entity("patients", entity_id)

    @app.get(
        "/api/v1/devices/{entity_id}",
        dependencies=[Depends(authorize)],
        response_model=Device,
        responses=read_errors,
        tags=["登錄"],
    )
    def read_device(entity_id: str) -> Patient | Device:
        return store.entity("devices", entity_id)

    @app.post(
        "/api/v1/measurements/heart-rate",
        dependencies=[Depends(authorize)],
        response_model=IngestReceipt,
        responses=errors
        | {201: {"model": IngestReceipt, "description": "首次保存量測"}},
        tags=["量測"],
    )
    def ingest(data: Measurement, response: Response) -> dict[str, Any]:
        record, duplicate = store.ingest(data)
        response.status_code = 200 if duplicate else 201
        return {"duplicate": duplicate, "measurement": record.model_dump(mode="json")}

    @app.post(
        "/api/v1/measurements/ecg",
        dependencies=[Depends(authorize)],
        response_model=IngestReceipt,
        responses=errors
        | {201: {"model": IngestReceipt, "description": "首次保存波形"}},
        tags=["量測"],
    )
    def ingest_ecg(data: EcgMeasurement, response: Response) -> dict[str, Any]:
        record, duplicate = store.ingest(data)
        response.status_code = 200 if duplicate else 201
        return {"duplicate": duplicate, "measurement": record.model_dump(mode="json")}

    @app.get(
        "/api/v1/measurements/{measurement_id}",
        dependencies=[Depends(authorize)],
        response_model=MeasurementRecord | EcgRecord,
        responses=read_errors,
        tags=["量測"],
    )
    def read_measurement(measurement_id: str) -> Record:
        return store.measurement(measurement_id)

    @app.get(
        "/api/v1/measurements/{measurement_id}/export/fhir",
        dependencies=[Depends(authorize)],
        responses=read_errors
        | {501: {"model": SandboxError, "description": "ECG 的 FHIR 映射尚未驗證"}},
        tags=["選用匯出"],
    )
    def export_fhir(measurement_id: str) -> Response:
        record = store.measurement(measurement_id)
        if not isinstance(record, MeasurementRecord):
            raise HTTPException(501, "ECG 的 FHIR 映射尚未驗證，請使用 Cross 原生查詢")
        return Response(
            json.dumps(observation(record)),
            media_type="application/fhir+json",
        )

    return app


def app_factory() -> FastAPI:
    return create_app(
        Path(os.environ.get("CROSS_SANDBOX_DB", "/tmp/cross-sandbox.sqlite3")),
        os.environ.get("CROSS_SANDBOX_TOKEN", ""),
    )
