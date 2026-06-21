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


def test_rollup_ngsi_ld_unchanged_type():
    a = _mk()
    e = a.to_ngsi_ld()
    assert e["type"] == "CropHealthAssessment"
    assert e["id"] == "urn:ngsi-ld:CropHealthAssessment:p1-20260621"
    assert "hasAgriParcelZone" not in e
