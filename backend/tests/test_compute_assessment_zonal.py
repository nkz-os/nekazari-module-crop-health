import pytest
from datetime import datetime, timezone

from app.services import pipeline
from app.services.zonation import Zone
from app.schemas import CropHealthAssessment, Severity


_Z0 = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
_Z1 = {"type": "Polygon", "coordinates": [[[1, 0], [1, 1], [2, 1], [2, 0], [1, 0]]]}


def _patch_crop_level(monkeypatch):
    async def _crop(pid, tid):
        return {"species": "Zea mays", "plantingDate": "2026-04-15", "variety": "MAS 26 T"}

    async def _stages(species):
        from app.schemas import StageTable
        return StageTable(stages={"emergence": (0.0, 90.0), "vegetative": (90.0, 520.0)})

    async def _gdd(*a, **k):
        return {"gdd_total": 300.0}

    monkeypatch.setattr(pipeline, "_read_assigned_crop", _crop, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_phenology_stages", _stages)
    monkeypatch.setattr(pipeline, "_fetch_gdd", _gdd, raising=False)


@pytest.mark.asyncio
async def test_two_zones_emit_two_zone_assessments_plus_rollup(monkeypatch):
    _patch_crop_level(monkeypatch)
    published = []

    async def _pub(entity, tid):
        published.append(entity)
        return True

    async def _zones(pid, tid, geom):
        return [Zone("z0", _Z0, urn="urn:ngsi-ld:AgriParcelZone:t:p1:z0"),
                Zone("z1", _Z1, urn="urn:ngsi-ld:AgriParcelZone:t:p1:z1")]

    monkeypatch.setattr(pipeline, "_publish_assessment", _pub, raising=False)
    monkeypatch.setattr(pipeline, "resolve_zones", _zones, raising=False)

    out = await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t")
    types = [e["type"] for e in published]
    assert types.count("CropHealthZoneAssessment") == 2
    assert types.count("CropHealthAssessment") == 1
    # rollup returned, no zone identity
    assert out is not None
    assert out.zone_id is None
    # zone entities carry the real zone URN ref
    zone_entities = [e for e in published if e["type"] == "CropHealthZoneAssessment"]
    assert {e["hasAgriParcelZone"]["object"] for e in zone_entities} == {
        "urn:ngsi-ld:AgriParcelZone:t:p1:z0",
        "urn:ngsi-ld:AgriParcelZone:t:p1:z1",
    }


@pytest.mark.asyncio
async def test_fallback_no_zones_only_rollup(monkeypatch):
    _patch_crop_level(monkeypatch)
    published = []

    async def _pub(entity, tid):
        published.append(entity)
        return True

    async def _zones(pid, tid, geom):
        return [Zone("parcel", _Z0)]

    monkeypatch.setattr(pipeline, "_publish_assessment", _pub, raising=False)
    monkeypatch.setattr(pipeline, "resolve_zones", _zones, raising=False)

    out = await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t")
    types = [e["type"] for e in published]
    assert "CropHealthZoneAssessment" not in types
    assert types.count("CropHealthAssessment") == 1
    assert out.phenology_stage == "vegetative"  # derived from gdd=300


def test_aggregate_rollup_picks_worst_zone():
    now = datetime(2026, 6, 21, tzinfo=timezone.utc)

    def _za(zone_id, sev):
        return CropHealthAssessment(parcel_id="p1", assessed_at=now, zone_id=zone_id, overall_severity=sev)

    zones = [_za("z0", Severity.LOW), _za("z1", Severity.CRITICAL), _za("z2", Severity.MEDIUM)]
    rollup = pipeline._aggregate_rollup("p1", zones)
    assert rollup.overall_severity == Severity.CRITICAL
    assert rollup.zone_id is None
    assert rollup.parcel_id == "p1"
