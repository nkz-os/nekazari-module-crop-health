"""Zone assessments link to AgriManagementZone; the API shows only the current run's levels."""
from datetime import datetime, timezone

import pytest

from app.api.assessment_mapper import (
    extract_zone_id,
    extract_zone_urn,
    map_entity_to_zone_assessment,
)
from app.api.assessments import _live_zone_assessments
from app.schemas import CropHealthAssessment
from app.services.zonation import Zone

RUN = "a1" * 16
OLD_RUN = "b2" * 16
AMZ_URN = "urn:ngsi-ld:AgriManagementZone:p1:a1a1a1a1:L1"
POLY = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}
DAY = "20261117"
NS = "https://nkz-os.org/ns/"


def assessment(**kw):
    return CropHealthAssessment(
        parcel_id="p1", assessed_at=datetime(2026, 11, 17, tzinfo=timezone.utc), **kw
    )


def _live(*levels):
    return [
        Zone(
            zone_id=lv, geometry=POLY, urn=f"urn:ngsi-ld:AgriManagementZone:p1:a1a1a1a1:L{i + 1}",
            zone_level=lv, zone_version=RUN, zone_rank=i + 1,
        )
        for i, lv in enumerate(levels)
    ]


def _ent(zone_id, at, run=RUN, urn=None, severity="LOW", **extra):
    e = {
        "id": f"urn:ngsi-ld:CropHealthZoneAssessment:p1-{zone_id}-{at}",
        "hasAgriParcel": "urn:ngsi-ld:AgriParcel:p1",
        "zoneId": zone_id,
        "overallSeverity": severity,
        "assessedAt": at,
        "nkz:zoneRank": 1,
        **extra,
    }
    if run is not None:
        e["nkz:zoningRunId"] = run
    e["hasAgriManagementZone" if urn and "AgriManagementZone" in urn else "hasAgriParcelZone"] = (
        urn or f"urn:ngsi-ld:AgriParcelZone:t:p1:{zone_id}"
    )
    return e


def test_zone_entity_points_to_management_zone():
    e = assessment(zone_id="high", zone_level="high", zone_urn=AMZ_URN, zone_version=RUN).to_zone_ngsi_ld()
    assert e["id"] == f"urn:ngsi-ld:CropHealthZoneAssessment:p1-high-{DAY}"
    assert e["hasAgriManagementZone"]["object"] == AMZ_URN and "hasAgriParcelZone" not in e
    assert e["nkz:zoneLevel"]["value"] == "high" and e["nkz:zoningRunId"]["value"] == RUN


def test_zone_entity_without_management_zone_urn_is_refused():
    with pytest.raises(ValueError):
        assessment(zone_id="high", zone_level="high").to_zone_ngsi_ld()


@pytest.mark.parametrize("key", ["hasAgriManagementZone", "nkz:hasAgriManagementZone", NS + "hasAgriManagementZone"])
def test_extract_zone_urn_reads_three_forms(key):
    assert extract_zone_urn({key: {"type": "Relationship", "object": AMZ_URN}}) == AMZ_URN
    assert extract_zone_urn({key: AMZ_URN}) == AMZ_URN


def test_extract_zone_urn_ignores_terrain_relation():
    assert extract_zone_urn({"hasAgriParcelZone": "urn:ngsi-ld:AgriParcelZone:t:p1:z1"}) == ""
    assert extract_zone_urn({}) == ""


def test_extract_zone_id_of_management_zone_uses_level_not_urn_tail():
    e = {"hasAgriManagementZone": AMZ_URN, NS + "zoneLevel": "high"}
    assert extract_zone_id(e) == "high"


def test_mapper_exposes_zone_level_in_any_form():
    for key in ("zoneLevel", "nkz:zoneLevel", NS + "zoneLevel"):
        r = map_entity_to_zone_assessment({"zoneId": "low", key: "low", "hasAgriManagementZone": AMZ_URN})
        assert r["zoneLevel"] == "low"
    assert map_entity_to_zone_assessment({"zoneId": "z1"})["zoneLevel"] is None


def test_live_filter_keeps_current_levels_drops_terrain_and_missing_levels():
    live = _live("high", "medium")
    entities = [
        _ent("high", "2026-11-16T10:00:00Z", run=OLD_RUN, urn=AMZ_URN, severity="HIGH"),
        _ent("high", "2026-11-17T09:00:00Z", urn=AMZ_URN, severity="MEDIUM"),
        _ent("low", "2026-11-17T09:00:00Z", urn="urn:ngsi-ld:AgriManagementZone:p1:a1a1a1a1:L3"),
        _ent("zezw1-e11-E", "2026-11-17T09:00:00Z", run=None),
    ]
    out = _live_zone_assessments(entities, live, {})
    assert [z["zoneId"] for z in out] == ["high"]
    assert out[0]["overallSeverity"] == "MEDIUM"


def test_live_filter_requires_current_run():
    live = _live("high")
    # newer assessment, but of the previous geometry: never painted on the new one
    entities = [
        _ent("high", "2026-11-17T09:00:00Z", run=OLD_RUN, urn=AMZ_URN),
        _ent("high", "2026-11-17T10:00:00Z", run=None, urn=AMZ_URN),
    ]
    assert _live_zone_assessments(entities, live, {}) == []


def test_live_filter_reads_run_in_all_forms():
    live = _live("high")
    for key in ("zoningRunId", "nkz:zoningRunId", NS + "zoningRunId"):
        e = _ent("high", "2026-11-17T09:00:00Z", run=None, urn=AMZ_URN)
        e[key] = RUN
        assert len(_live_zone_assessments([e], live, {})) == 1


def test_zones_response_contract_for_mobile_and_agent():
    live = _live("high")
    e = _ent("high", "2026-11-17T09:00:00Z", urn=AMZ_URN, **{"nkz:zoneLevel": "high", "overallSeverity": "HIGH"})
    z = _live_zone_assessments([e], live, {"overallSeverity": "LOW"})[0]
    # nkz-mobile parseZones + agent crop_health adapter
    assert isinstance(z["zoneId"], str) and z["zoneId"] == "high"
    assert z["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert {"overallSeverity", "zoneRank", "differsFromParcel", "zoneLevel"} <= z.keys()
    assert z["zoneLevel"] == "high" and z["zoneRank"] == 1
