"""Back-compat guard: legacy CropHealthAssessment consumers (phenology-status,
listing, SP2 action-rules, reconcile) must NEVER receive zone entities. The
separation is by TYPE, so a ``type=CropHealthAssessment`` query can never match
a zone entity.
"""
from datetime import datetime, timezone

from app.schemas import CropHealthAssessment


def test_zone_and_rollup_have_distinct_types_and_ids():
    a = CropHealthAssessment(
        parcel_id="p1",
        assessed_at=datetime(2026, 6, 21, tzinfo=timezone.utc),
        zone_id="z2",
    )
    zone = a.to_zone_ngsi_ld()
    rollup = a.to_ngsi_ld()
    assert zone["type"] != rollup["type"]
    assert zone["id"] != rollup["id"]
    assert rollup["type"] == "CropHealthAssessment"
    assert zone["type"] == "CropHealthZoneAssessment"
    # rollup carries no zone relationship; zone does
    assert "hasAgriParcelZone" not in rollup
    assert "hasAgriParcelZone" in zone
    # ids live in disjoint URN namespaces
    assert rollup["id"].startswith("urn:ngsi-ld:CropHealthAssessment:")
    assert zone["id"].startswith("urn:ngsi-ld:CropHealthZoneAssessment:")
