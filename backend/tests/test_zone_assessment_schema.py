from datetime import datetime, timezone

from app.schemas import CropHealthAssessment


def _mk(**kw):
    return CropHealthAssessment(parcel_id="p1", assessed_at=datetime(2026, 6, 21, tzinfo=timezone.utc), **kw)


def test_zone_ngsi_ld_uses_zone_type_and_relationships():
    a = _mk(zone_id="z3", overall_severity="HIGH")
    e = a.to_zone_ngsi_ld()
    assert e["type"] == "CropHealthZoneAssessment"
    assert e["id"] == "urn:ngsi-ld:CropHealthZoneAssessment:p1-z3-20260621"
    assert e["hasAgriParcel"]["object"] == "urn:ngsi-ld:AgriParcel:p1"
    assert e["hasAgriParcelZone"]["object"] == "urn:ngsi-ld:AgriParcelZone:p1-z3"
    assert e["zoneId"]["value"] == "z3"


def test_zone_ngsi_ld_uses_real_zone_urn_when_present():
    a = _mk(zone_id="zABC-e3-N", zone_urn="urn:ngsi-ld:AgriParcelZone:montiko:p1:zABC-e3-N")
    e = a.to_zone_ngsi_ld()
    assert e["hasAgriParcelZone"]["object"] == "urn:ngsi-ld:AgriParcelZone:montiko:p1:zABC-e3-N"
    assert e["zoneId"]["value"] == "zABC-e3-N"


def test_rollup_ngsi_ld_unchanged_type():
    a = _mk()
    e = a.to_ngsi_ld()
    assert e["type"] == "CropHealthAssessment"
    assert e["id"] == "urn:ngsi-ld:CropHealthAssessment:p1-20260621"
    assert "hasAgriParcelZone" not in e


def test_soil_suitability_parses_graded_verdict_and_legacy():
    from app.schemas import SoilSuitability, CropHealthAssessment
    graded = SoilSuitability(verdict="unsuitable", reason="pH high",
                             confidence="medium", ph={"value": 8.1, "verdict": "unsuitable"})
    assert graded.verdict == "unsuitable"
    legacy = SoilSuitability(ph_match=False, overall="unsuitable", warnings=["x"])
    assert legacy.verdict is None and legacy.overall == "unsuitable"
    a = CropHealthAssessment(parcel_id="urn:p:1",
                             assessed_at=datetime(2026, 6, 21, tzinfo=timezone.utc),
                             soil_suitability=graded)
    assert a.soil_suitability.verdict == "unsuitable"
