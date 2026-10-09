import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sandbox.api import create_app

TOKEN = "sandbox-test-token-12345678901234567890"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
PATIENT = {
    "id": "demo-patient",
    "source_system": "demo-clinic",
    "external_id": "chart-001",
}
DEVICE = {
    "id": "demo-device",
    "source_system": "demo-vendor",
    "external_id": "serial-001",
    "manufacturer": "模擬廠商",
    "model": "模擬裝置",
    "firmware_version": "1.0",
}
PAYLOAD = {
    "event_id": "demo-001",
    "patient_id": "demo-patient",
    "device_id": "demo-device",
    "measured_at": "2026-10-06T10:00:00+08:00",
    "heart_rate": 72,
}
INGEST = "/api/v1/measurements/heart-rate"


def register(client: TestClient) -> None:
    assert (
        client.post("/api/v1/patients", json=PATIENT, headers=HEADERS).status_code
        == 201
    )
    assert (
        client.post("/api/v1/devices", json=DEVICE, headers=HEADERS).status_code == 201
    )


def test_roundtrip_retry_conflict_restart_and_export(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite3"
    with TestClient(create_app(path, TOKEN)) as client:
        register(client)
        first = client.post(INGEST, json=PAYLOAD, headers=HEADERS)
        assert first.status_code == 201
        record = first.json()["measurement"]
        assert "resourceType" not in record
        assert record["schema_version"] == "1.0"
        assert record["device"]["firmware_version"] == "1.0"
        assert record["patient"]["source_system"] == "demo-clinic"
        assert record["received_at"]
        retry = client.post(
            INGEST,
            json={**PAYLOAD, "measured_at": "2026-10-06T02:00:00Z"},
            headers=HEADERS,
        )
        assert retry.status_code == 200
        assert retry.json()["duplicate"] is True
        assert retry.json()["measurement"] == record
        assert (
            client.post(
                INGEST, json={**PAYLOAD, "heart_rate": 73}, headers=HEADERS
            ).status_code
            == 409
        )
    with TestClient(create_app(path, TOKEN)) as restarted:
        read = restarted.get(f"/api/v1/measurements/{record['id']}", headers=HEADERS)
        assert read.json() == record
        exported = restarted.get(
            f"/api/v1/measurements/{record['id']}/export/fhir", headers=HEADERS
        )
        assert exported.headers["content-type"] == "application/fhir+json"
        assert exported.json()["valueQuantity"]["code"] == "/min"
        assert exported.json()["subject"]["reference"] == "Patient/demo-patient"
        assert exported.json()["id"] == record["id"]
        assert (
            restarted.get(
                f"/api/v1/measurements/{record['id']}", headers=HEADERS
            ).json()
            == record
        )


def test_registration_identity_and_required_references(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "data.sqlite3", TOKEN)) as client:
        assert client.post(INGEST, json=PAYLOAD, headers=HEADERS).status_code == 422
        register(client)
        assert (
            client.post("/api/v1/devices", json=DEVICE, headers=HEADERS).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/devices",
                json={**DEVICE, "model": "different"},
                headers=HEADERS,
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/patients",
                json={**PATIENT, "id": "demo-other"},
                headers=HEADERS,
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/patients",
                json={**PATIENT, "id": "demo-other", "source_system": "other-clinic"},
                headers=HEADERS,
            ).status_code
            == 201
        )
        assert (
            client.get("/api/v1/devices/demo-device", headers=HEADERS).json() == DEVICE
        )
        assert (
            client.get("/api/v1/patients/demo-patient", headers=HEADERS).json()
            == PATIENT
        )
        assert (
            client.post(
                "/api/v1/devices",
                json={**DEVICE, "id": "demo-device-2", "external_id": "serial-002"},
                headers=HEADERS,
            ).status_code
            == 201
        )
        first = client.post(INGEST, json=PAYLOAD, headers=HEADERS)
        second = client.post(
            INGEST, json={**PAYLOAD, "device_id": "demo-device-2"}, headers=HEADERS
        )
        assert first.status_code == second.status_code == 201
        assert first.json()["measurement"]["id"] != second.json()["measurement"]["id"]


@pytest.mark.parametrize(
    "changes",
    [
        {"patient_id": "real-patient"},
        {"heart_rate": -1},
        {"heart_rate": 401},
        {"measured_at": "2026-10-06T10:00:00"},
        {"unexpected": 1},
        {"unit": "Hz"},
        {"schema_version": "2.0"},
    ],
)
def test_invalid_data(tmp_path: Path, changes: dict[str, Any]) -> None:
    with TestClient(create_app(tmp_path / "data.sqlite3", TOKEN)) as client:
        register(client)
        assert (
            client.post(
                INGEST, json={**PAYLOAD, **changes}, headers=HEADERS
            ).status_code
            == 422
        )


def test_auth_and_missing_record(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "data.sqlite3", TOKEN)) as client:
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            assert client.post(INGEST, json=PAYLOAD, headers=headers).status_code == 401
            assert (
                client.post(
                    "/api/v1/patients", json=PATIENT, headers=headers
                ).status_code
                == 401
            )
            assert (
                client.post("/api/v1/devices", json=DEVICE, headers=headers).status_code
                == 401
            )
            assert (
                client.get("/api/v1/devices/demo-device", headers=headers).status_code
                == 401
            )
            assert (
                client.get("/api/v1/patients/demo-patient", headers=headers).status_code
                == 401
            )
            assert (
                client.get("/api/v1/measurements/missing", headers=headers).status_code
                == 401
            )
            assert (
                client.get(
                    "/api/v1/measurements/missing/export/fhir", headers=headers
                ).status_code
                == 401
            )
        assert (
            client.get("/api/v1/measurements/missing", headers=HEADERS).status_code
            == 404
        )
        assert (
            client.get(
                "/api/v1/measurements/missing/export/fhir", headers=HEADERS
            ).status_code
            == 404
        )


def test_concurrent_retry_creates_one_measurement(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "data.sqlite3", TOKEN)) as client:
        register(client)
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(
                pool.map(
                    lambda _: client.post(INGEST, json=PAYLOAD, headers=HEADERS),
                    range(6),
                )
            )
        assert sorted(response.status_code for response in responses) == [
            200,
            200,
            200,
            200,
            200,
            201,
        ]
        assert (
            len({response.json()["measurement"]["id"] for response in responses}) == 1
        )


def ecg_payload() -> dict[str, Any]:
    waveform = json.loads(
        (Path(__file__).parent / "fixtures/ecg-waveform.json").read_text()
    )
    return {key: value for key, value in PAYLOAD.items() if key != "heart_rate"} | {
        "event_id": "demo-ecg-001",
        "unit": "uV",
        "waveform": waveform,
    }


def test_ecg_roundtrip_retry_restart_and_explicit_export_limit(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite3"
    payload = ecg_payload()
    with TestClient(create_app(path, TOKEN)) as client:
        register(client)
        first = client.post("/api/v1/measurements/ecg", json=payload, headers=HEADERS)
        assert first.status_code == 201
        record = first.json()["measurement"]
        assert record["kind"] == "ecg"
        assert record["waveform"] == payload["waveform"]
        assert record["sample_count"] == 500
        assert record["duration_ms"] == 2000
        assert "heart_rate" not in record
        retry = client.post("/api/v1/measurements/ecg", json=payload, headers=HEADERS)
        assert retry.status_code == 200
        assert retry.json() == {"duplicate": True, "measurement": record}
        changed = copy.deepcopy(payload)
        changed["waveform"]["sample_rate_hz"] = 500
        assert (
            client.post(
                "/api/v1/measurements/ecg", json=changed, headers=HEADERS
            ).status_code
            == 409
        )
        assert (
            client.post(
                INGEST,
                json=PAYLOAD | {"event_id": payload["event_id"]},
                headers=HEADERS,
            ).status_code
            == 409
        )
    with TestClient(create_app(path, TOKEN)) as client:
        assert (
            client.get(f"/api/v1/measurements/{record['id']}", headers=HEADERS).json()
            == record
        )
        assert (
            client.get(
                f"/api/v1/measurements/{record['id']}/export/fhir", headers=HEADERS
            ).status_code
            == 501
        )
        assert client.post("/api/v1/measurements/ecg", json=payload).status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"samples": [1.5, 2]},
        {"samples": [True, 2]},
        {"samples": [100001, 0]},
        {"samples": [1]},
        {"samples": [0] * 5001},
        {"sample_sha256": "0" * 64},
        {"lead": "II"},
        {"sample_rate_hz": 49},
        {"sample_rate_hz": 250.0},
        {"sample_rate_hz": 1001},
        {"samples": [0] * 501, "sample_rate_hz": 50},
        {"signal_origin": "device"},
        {"filtering": "unknown"},
        {"calibration": "raw-adc"},
    ],
)
def test_ecg_rejects_corrupt_or_unsupported_waveform(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    with TestClient(create_app(tmp_path / "data.sqlite3", TOKEN)) as client:
        register(client)
        payload = ecg_payload()
        payload["waveform"].update(changes)
        assert (
            client.post(
                "/api/v1/measurements/ecg", json=payload, headers=HEADERS
            ).status_code
            == 422
        )
