"""Weighted parcel rollup, input fidelity serialisation and differsFromParcel."""
from datetime import datetime, timezone

import pytest

from app.api.assessment_mapper import differs_from_parcel, map_entity_to_zone_assessment
from app.schemas import (
    CompositeStressResult, CropHealthAssessment, RecommendedAction, Severity,
)
from app.services import pipeline

NOW = datetime(2026, 6, 21, tzinfo=timezone.utc)


def _za(zone_id, composite, sev, action=RecommendedAction.NO_ACTION, rank=None):
    return CropHealthAssessment(
        parcel_id="p1", assessed_at=NOW, zone_id=zone_id, zone_rank=rank,
        overall_severity=sev, recommended_action=action,
        composite_stress=CompositeStressResult(composite_index=composite),
    )


def test_weighted_rollup_numerics_worst_severity():
    a = _za("z0", 20.0, Severity.LOW, rank=1)
    b = _za("z1", 60.0, Severity.HIGH, RecommendedAction.IRRIGATE_IMMEDIATE, rank=2)
    r = pipeline._aggregate_rollup("p1", [a, b], {"z0": 0.75, "z1": 0.25})
    assert r.composite_stress.composite_index == pytest.approx(30.0)
    assert r.overall_severity == Severity.HIGH
    assert r.recommended_action == RecommendedAction.IRRIGATE_IMMEDIATE
    assert r.zone_spread == pytest.approx(40.0)
    assert r.worst_zone_id == "z1"
    assert r.worst_zone_rank == 2
    assert r.zone_id is None
    # inputs are not mutated
    assert b.composite_stress.composite_index == 60.0


def test_single_zone_rollup_is_identical_to_worst_copy():
    a = _za(None, 42.0, Severity.MEDIUM)
    r = pipeline._aggregate_rollup("p1", [a], {"parcel": 1.0})
    expected = a.model_copy()
    expected.parcel_id = "p1"
    assert r.to_ngsi_ld() == expected.to_ngsi_ld()
    assert "nkz:zoneSpread" not in r.to_ngsi_ld()


def test_rollup_entity_carries_worst_zone_and_spread():
    a = _za("z0", 20.0, Severity.LOW, rank=1)
    b = _za("z1", 60.0, Severity.HIGH, rank=2)
    e = pipeline._aggregate_rollup("p1", [a, b], {"z0": 0.5, "z1": 0.5}).to_ngsi_ld()
    assert e["nkz:worstZoneId"] == {"type": "Property", "value": "z1"}
    assert e["nkz:worstZoneRank"] == {"type": "Property", "value": 2}
    assert e["nkz:zoneSpread"] == {"type": "Property", "value": 40.0}


def test_rollup_skips_none_composite_and_renormalises():
    a = _za("z0", 20.0, Severity.LOW)
    b = CropHealthAssessment(parcel_id="p1", assessed_at=NOW, zone_id="z1", overall_severity=Severity.HIGH,
                             composite_stress=None)
    c = _za("z2", 40.0, Severity.LOW)
    r = pipeline._aggregate_rollup("p1", [a, b, c], {"z0": 0.25, "z1": 0.5, "z2": 0.25})
    # worst (z1) has no composite object: untouched, spread from the two present values
    assert r.zone_spread == pytest.approx(20.0)


def test_zone_entity_emits_fidelity_version_rank():
    a = _za("z0", 20.0, Severity.LOW, rank=3)
    a.input_fidelity = {"ndvi": "zone_specific", "sar": "parcel_inherited"}
    a.zone_version = "v7"
    e = a.to_zone_ngsi_ld()
    assert e["nkz:inputFidelity"] == {"type": "Property",
                                      "value": {"ndvi": "zone_specific", "sar": "parcel_inherited"}}
    assert e["nkz:zoneVersion"] == {"type": "Property", "value": "v7"}
    assert e["nkz:zoneRank"] == {"type": "Property", "value": 3}
    plain = _za("z0", 20.0, Severity.LOW).to_zone_ngsi_ld()
    assert "nkz:inputFidelity" not in plain


def test_all_inherited_zone_does_not_differ_even_with_sensor_nearby():
    zone = {"sensorNearby": True, "cwsiValue": 0.9, "inputFidelity": {"ndvi": "parcel_inherited", "sar": "parcel_inherited"}}
    assert differs_from_parcel(zone, {"cwsiValue": 0.1}) is False


def test_zone_specific_input_keeps_existing_rule():
    zone = {"sensorNearby": True, "inputFidelity": {"ndvi": "zone_specific"}}
    assert differs_from_parcel(zone, {}) is True
    zone = {"sensorNearby": False, "cwsiValue": 0.5, "inputFidelity": {"ndvi": "zone_specific"}}
    assert differs_from_parcel(zone, {"cwsiValue": 0.2}) is True


def test_no_fidelity_keeps_existing_rule():
    assert differs_from_parcel({"sensorNearby": True}, {}) is True


def test_mapper_passes_fidelity_rank_version_wetness_through():
    entity = {
        "id": "urn:ngsi-ld:CropHealthZoneAssessment:p1-z0-20260621", "type": "CropHealthZoneAssessment",
        "hasAgriParcelZone": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcelZone:acme:p1:z0"},
        "assessedAt": {"type": "Property", "value": NOW.isoformat()},
        "nkz:inputFidelity": {"type": "Property", "value": {"ndvi": "zone_specific"}},
        "https://nkz-os.org/ns/zoneRank": {"type": "Property", "value": 2},
        "nkz:zoneVersion": {"type": "Property", "value": "v7"},
        "nkz:wetnessClass": {"type": "Property", "value": "wet"},
    }
    z = map_entity_to_zone_assessment(entity)
    assert z["inputFidelity"] == {"ndvi": "zone_specific"}
    assert z["zoneRank"] == 2
    assert z["zoneVersion"] == "v7"
    assert z["wetnessClass"] == "wet"
    bare = map_entity_to_zone_assessment({k: v for k, v in entity.items() if not k.startswith(("nkz", "https"))})
    assert bare["inputFidelity"] == {} and bare["zoneRank"] is None and bare["wetnessClass"] is None
