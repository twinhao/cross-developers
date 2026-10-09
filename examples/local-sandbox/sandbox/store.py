"""僅供本機沙盒的 SQLite 保存與交易。"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import TypeAdapter

from sandbox.models import (
    Device,
    EcgMeasurement,
    EcgRecord,
    Measurement,
    MeasurementRecord,
    Patient,
    Record,
)

record_adapter: TypeAdapter[Record] = TypeAdapter(Record)


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            for table in ("cross_patients", "cross_devices"):
                db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
                    id TEXT PRIMARY KEY, source_system TEXT NOT NULL,
                    external_id TEXT NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(source_system, external_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS cross_measurements (
                id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                patient_id TEXT NOT NULL, event_id TEXT NOT NULL,
                payload TEXT NOT NULL, record TEXT NOT NULL,
                UNIQUE(device_id, event_id),
                FOREIGN KEY(device_id) REFERENCES cross_devices(id),
                FOREIGN KEY(patient_id) REFERENCES cross_patients(id))""")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def register(
        self, data: Patient | Device, kind: Literal["patients", "devices"]
    ) -> bool:
        table = f"cross_{kind}"
        payload = data.model_dump_json()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                f"SELECT payload FROM {table} WHERE id=?", (data.id,)
            ).fetchone()
            if row:
                if row[0] != payload:
                    raise HTTPException(409, "識別碼已登錄不同內容")
                return False
            try:
                db.execute(
                    f"INSERT INTO {table} VALUES (?, ?, ?, ?)",
                    (
                        data.id,
                        data.source_system,
                        data.external_id,
                        payload,
                    ),
                )
            except sqlite3.IntegrityError:
                raise HTTPException(409, "來源系統的外部識別碼已登錄")
        return True

    def entity(
        self, kind: Literal["patients", "devices"], entity_id: str
    ) -> Patient | Device:
        with self.connect() as db:
            row = db.execute(
                f"SELECT payload FROM cross_{kind} WHERE id=?", (entity_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(404, "查無登錄資料")
        model = Patient if kind == "patients" else Device
        return model.model_validate_json(row[0])

    def ingest(self, data: Measurement | EcgMeasurement) -> tuple[Record, bool]:
        payload = data.model_dump_json()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload, record FROM cross_measurements WHERE device_id=? AND event_id=?",
                (data.device_id, data.event_id),
            ).fetchone()
            if row:
                if row[0] != payload:
                    raise HTTPException(409, "同一設備的 event_id 已使用不同內容")
                return record_adapter.validate_json(row[1]), True
            patient = db.execute(
                "SELECT payload FROM cross_patients WHERE id=?", (data.patient_id,)
            ).fetchone()
            device = db.execute(
                "SELECT payload FROM cross_devices WHERE id=?", (data.device_id,)
            ).fetchone()
            if patient is None or device is None:
                raise HTTPException(422, "請先登錄病人與設備")
            common = {
                "id": str(uuid4()),
                "received_at": datetime.now(UTC),
                "patient": Patient.model_validate_json(patient[0]),
                "device": Device.model_validate_json(device[0]),
            }
            record: Record
            if isinstance(data, EcgMeasurement):
                record = EcgRecord.model_validate(
                    data.model_dump()
                    | common
                    | {
                        "sample_count": len(data.waveform.samples),
                        "duration_ms": len(data.waveform.samples)
                        * 1000
                        / data.waveform.sample_rate_hz,
                    }
                )
            else:
                record = MeasurementRecord.model_validate(data.model_dump() | common)
            db.execute(
                "INSERT INTO cross_measurements VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    data.device_id,
                    data.patient_id,
                    data.event_id,
                    payload,
                    record.model_dump_json(),
                ),
            )
        return record, False

    def measurement(self, measurement_id: str) -> Record:
        with self.connect() as db:
            row = db.execute(
                "SELECT record FROM cross_measurements WHERE id=?", (measurement_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(404, "查無量測")
        return record_adapter.validate_json(row[0])
