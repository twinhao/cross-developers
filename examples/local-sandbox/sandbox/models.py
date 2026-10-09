"""Cross 原生資料契約；FHIR 格式僅在交換邊界產生。"""

import hashlib
import struct
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

DemoId = Annotated[str, Field(pattern=r"^demo-[A-Za-z0-9.-]{1,50}$")]
ShortId = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Patient(Contract):
    id: DemoId
    source_system: ShortId
    external_id: ShortId


class Device(Contract):
    id: DemoId
    source_system: ShortId
    external_id: ShortId
    manufacturer: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    firmware_version: str = Field(min_length=1, max_length=64)


class MeasurementEnvelope(Contract):
    schema_version: Literal["1.0"] = "1.0"
    event_id: ShortId
    patient_id: DemoId
    device_id: DemoId
    measured_at: AwareDatetime

    @field_validator("measured_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class Measurement(MeasurementEnvelope):
    heart_rate: float = Field(gt=0, le=400, allow_inf_nan=False)
    unit: Literal["/min"] = "/min"


class MeasurementRecord(Measurement):
    id: str
    kind: Literal["heart_rate"] = "heart_rate"
    received_at: AwareDatetime
    patient: Patient
    device: Device


class EcgWaveform(Contract):
    lead: Literal["I"]
    sample_rate_hz: int = Field(strict=True, ge=50, le=1000)
    samples: list[Annotated[int, Field(strict=True, ge=-100000, le=100000)]] = Field(
        min_length=2, max_length=5000
    )
    sample_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    signal_origin: Literal["simulator"]
    calibration: Literal["physical-microvolts"]
    filtering: Literal["none"]

    @model_validator(mode="after")
    def validate_waveform(self) -> EcgWaveform:
        if len(self.samples) > self.sample_rate_hz * 10:
            raise ValueError("沙盒波形最多 10 秒")
        packed = struct.pack(f"<{len(self.samples)}i", *self.samples)
        if hashlib.sha256(packed).hexdigest() != self.sample_sha256:
            raise ValueError("波形校驗碼不符")
        return self


class EcgMeasurement(MeasurementEnvelope):
    unit: Literal["uV"] = "uV"
    waveform: EcgWaveform


class EcgRecord(EcgMeasurement):
    id: str
    kind: Literal["ecg"] = "ecg"
    received_at: AwareDatetime
    patient: Patient
    device: Device
    sample_count: int
    duration_ms: float


Record = MeasurementRecord | EcgRecord


class IngestReceipt(Contract):
    duplicate: bool
    measurement: Record


class SandboxError(Contract):
    detail: str | list[dict[str, Any]]
