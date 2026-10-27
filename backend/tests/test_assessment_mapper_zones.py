"""Worst-zone fields reach the parcel assessment dict in all three spellings."""
import pytest

from app.api.assessment_mapper import map_entity_to_assessment, map_entity_to_zone_assessment

NS = "https://nkz-os.org/ns/"


def _entity(prefix: str) -> dict:
    return {
        "id": "urn:ngsi-ld:CropHealthAssessment:acme:p1",
        "hasAgriParcel": "urn:ngsi-ld:AgriParcel:p1",
        f"{prefix}worstZoneRank": {"type": "Property", "value": 3},
        f"{prefix}worstZoneId": {"type": "Property", "value": "z3"},
        f"{prefix}zoneSpread": {"type": "Property", "value": 12.5},
    }


@pytest.mark.parametrize("prefix", ["nkz:", NS, ""])
def test_worst_zone_fields_mapped(prefix):
    out = map_entity_to_assessment(_entity(prefix))
    assert out["worstZoneRank"] == 3
    assert out["worstZoneId"] == "z3"
    assert out["zoneSpread"] == 12.5


def test_worst_zone_fields_absent_are_none():
    out = map_entity_to_assessment({"id": "x", "hasAgriParcel": "urn:ngsi-ld:AgriParcel:p1"})
    assert out["worstZoneRank"] is None and out["worstZoneId"] is None and out["zoneSpread"] is None


def test_rank_string_with_decimal_does_not_raise():
    e = _entity("nkz:")
    e["nkz:worstZoneRank"] = {"type": "Property", "value": "3.0"}
    assert map_entity_to_assessment(e)["worstZoneRank"] == 3
    e["nkz:worstZoneRank"] = {"type": "Property", "value": "abc"}
    assert map_entity_to_assessment(e)["worstZoneRank"] is None


def test_zone_rank_guard():
    e = {"id": "x", "hasAgriParcel": "urn:ngsi-ld:AgriParcel:p1", "zoneId": "z1",
         "nkz:zoneRank": {"type": "Property", "value": "2.0"}}
    assert map_entity_to_zone_assessment(e)["zoneRank"] == 2
    e["nkz:zoneRank"] = {"type": "Property", "value": "n/a"}
    assert map_entity_to_zone_assessment(e)["zoneRank"] is None
