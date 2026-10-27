import pytest
from datetime import datetime, timezone

from app.services import pipeline
from app.services.zonation import Zone
from app.schemas import CropHealthAssessment, Severity


@pytest.fixture(autouse=True)
def _no_orion_cleanup(monkeypatch):
    """No real Orion call from the stale-attribute cleanup after a publish."""
    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "_clear_stale_water_stress", _noop)


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

    async def _season_in_progress(parcel_id, tenant_id):
        return "2026-04-15"  # a sown crop; season resolution is not under test here

    monkeypatch.setattr(pipeline.context_client, "resolve_season_start", _season_in_progress)


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


@pytest.mark.asyncio
async def test_zone_sensor_ctx_wiring_and_parcel_fallback(monkeypatch):
    _patch_crop_level(monkeypatch)
    seen = {}

    async def _pub(entity, tid):
        return True

    async def _zones(pid, tid, geom):
        return [Zone("zA", _Z0, urn="urn:ngsi-ld:AgriParcelZone:t:p1:zA"),
                Zone("zB", _Z1, urn="urn:ngsi-ld:AgriParcelZone:t:p1:zB")]

    async def _sensors(pid, tid):
        return [{"device_id": "d1", "lon": 0.5, "lat": 0.5, "readings": {"air_temp_c": 24.0},
                 "air_temp_c": 24.0}]

    async def _daily(*a, **k):
        return {}

    real = pipeline._assess_zone

    async def _spy(zone, *args, **kwargs):
        seen[zone.zone_id] = args[4]  # sensor_ctx positional
        return await real(zone, *args, **kwargs)

    monkeypatch.setattr(pipeline, "_publish_assessment", _pub, raising=False)
    monkeypatch.setattr(pipeline, "resolve_zones", _zones, raising=False)
    monkeypatch.setattr(pipeline, "_gather_parcel_sensors", _sensors)
    monkeypatch.setattr(pipeline, "_fetch_zone_daily", _daily)
    monkeypatch.setattr(pipeline, "_assess_zone", _spy)

    parcel_ctx = {"air_temp_c": 18.0}
    await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t", sensor_ctx=parcel_ctx)
    assert seen["zA"] == {"air_temp_c": 24.0}
    assert seen["zB"] == parcel_ctx


def _day_rows(n, t_min, t_max):
    return [{"date": f"2026-05-{d:02d}", "tMin": t_min, "tMax": t_max} for d in range(1, n + 1)]


async def _run_gdd(monkeypatch, zones, daily):
    _patch_crop_level(monkeypatch)
    published = []

    async def _pub(entity, tid):
        published.append(entity)
        return True

    async def _zones(pid, tid, geom):
        return zones

    async def _no_sensors(pid, tid):
        return []

    async def _daily(*a, **k):
        return daily

    monkeypatch.setattr(pipeline, "_publish_assessment", _pub, raising=False)
    monkeypatch.setattr(pipeline, "resolve_zones", _zones, raising=False)
    monkeypatch.setattr(pipeline, "_gather_parcel_sensors", _no_sensors)
    monkeypatch.setattr(pipeline, "_fetch_zone_daily", _daily)
    seen = {}
    real = pipeline._assess_zone

    async def _spy(zone, *args, **kwargs):
        a = await real(zone, *args, **kwargs)
        seen[zone.zone_id] = a
        return a

    monkeypatch.setattr(pipeline, "_assess_zone", _spy)
    await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t")
    return seen


@pytest.mark.asyncio
async def test_zone_gdd_is_parcel_plus_delta(monkeypatch):
    zones = [Zone("zA", _Z0, urn="urn:ngsi-ld:AgriParcelZone:t:p1:zA", area_ha=1.0),
             Zone("zB", _Z1, urn="urn:ngsi-ld:AgriParcelZone:t:p1:zB", area_ha=1.0)]
    seen = await _run_gdd(monkeypatch, zones,
                          {"zA": _day_rows(10, 8, 22), "zB": _day_rows(10, 9, 23)})
    assert seen["zA"].gdd_accumulated == pytest.approx(295.0)  # parcel 300 - 5
    assert seen["zB"].gdd_accumulated == pytest.approx(305.0)


@pytest.mark.asyncio
async def test_whole_parcel_gdd_unchanged(monkeypatch):
    seen = await _run_gdd(monkeypatch, [Zone("parcel", _Z0)], {"parcel": _day_rows(10, 8, 22)})
    assert seen["parcel"].gdd_accumulated == pytest.approx(300.0)


@pytest.mark.asyncio
async def test_non_numeric_tmin_does_not_sink_the_assessment(monkeypatch):
    zones = [Zone("zA", _Z0, urn="urn:ngsi-ld:AgriParcelZone:t:p1:zA", area_ha=1.0),
             Zone("zB", _Z1, urn="urn:ngsi-ld:AgriParcelZone:t:p1:zB", area_ha=1.0)]
    bad = [{"date": "2026-05-01", "tMin": "n/a", "tMax": 22}] * 10
    seen = await _run_gdd(monkeypatch, zones, {"zA": bad, "zB": _day_rows(10, 9, 23)})
    assert seen["zA"].gdd_accumulated == pytest.approx(300.0)
    assert seen["zB"].gdd_accumulated == pytest.approx(300.0)

