from app.api import phenology as ph


def test_envelope_high_on_iot_sensor():
    status = {
        "currentStage": "flowering",
        "deviation": "ahead",
        "dataFidelity": "iot_sensor",
        "phenologySource": "bioorchestrator",
    }
    ag = ph._status_agronomic(status)
    assert ag["currentStage"]["value"] == "flowering"
    assert ag["currentStage"]["confidence"] == "high"
    assert ag["currentStage"]["fidelity"] == "iot_sensor"
    assert ag["currentStage"]["source"]["short"] == "bioorchestrator"
    assert ag["deviation"]["value"] == "ahead"


def test_envelope_medium_on_parcel_weather():
    status = {"currentStage": "vegetative", "deviation": "on_track",
              "dataFidelity": "parcel_weather", "phenologySource": "default"}
    ag = ph._status_agronomic(status)
    assert ag["currentStage"]["confidence"] == "medium"
    assert ag["currentStage"]["source"]["short"] == "default"


def test_envelope_low_and_note_on_unavailable():
    status = {"currentStage": "unknown", "deviation": "on_track",
              "dataFidelity": "unavailable", "phenologySource": "default"}
    ag = ph._status_agronomic(status)
    assert ag["currentStage"]["confidence"] == "low"
    assert ag["currentStage"]["notes"]  # explains the assumption
