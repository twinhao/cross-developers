"""讀取 Cross 資料後轉換，不建立第二份臨床主資料。"""

from typing import Any

from sandbox.models import MeasurementRecord


def observation(data: MeasurementRecord) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": data.id,
        "identifier": [
            {
                "system": f"urn:cross:sandbox:device:{data.device_id}:event",
                "value": data.event_id,
            }
        ],
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "vital-signs",
                    }
                ]
            }
        ],
        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
        "subject": {"reference": f"Patient/{data.patient_id}"},
        "device": {"reference": f"Device/{data.device_id}"},
        "effectiveDateTime": data.measured_at.isoformat(),
        "valueQuantity": {
            "value": data.heart_rate,
            "unit": "beats/minute",
            "system": "http://unitsofmeasure.org",
            "code": data.unit,
        },
    }
