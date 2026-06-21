"""Task 6 — sensor webhook (`trigger`) does a deterministic full multi-zone
recompute that PRESERVES the device-window engines (CWSI/MDS) by attributing
them to the device's zone, while whole-parcel mode stays byte-identical to the
legacy behaviour. The engine core is mocked as a recorder so the test asserts
the WIRING (which zone gets redis_state + metric_type), not engine internals.
"""
import types

import pytest

from app.services import pipeline
from app.services.zonation import Zone
from app.schemas import Severity, MetricType


_Z0 = {"type": "Polygon", "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]}
_Z1 = {"type": "Polygon", "coordinates": [[[10, 0], [10, 10], [20, 10], [20, 0], [10, 0]]]}


class _Redis:
    async def get_soil_water(self, *a, **k):
        return None

    async def get_irrigation_24h(self, *a, **k):
        return 0.0


def _patch_trigger(monkeypatch, *, zones, device_coords):
    async def _none(*a, **k):
        return None

    async def _stages(species):
        from app.schemas import StageTable
        return StageTable(stages={"vegetative": (90.0, 520.0)})

    async def _crop(*a, **k):
        return {"plantingDate": "2026-04-15"}

    async def _gdd(*a, **k):
        return {"gdd_total": 300.0}

    async def _params(*a, **k):
        return types.SimpleNamespace(stage="vegetative", kc=1.0, mds_ref=100.0, ky=0.45)

    async def _coords(*a, **k):
        return (43.0, -2.0)

    async def _weather(*a, **k):
        return types.SimpleNamespace(temp_air=25.0)

    async def _soil(*a, **k):
        return types.SimpleNamespace(has_data=False)

    async def _geom(*a, **k):
        return _Z0

    async def _zones(*a, **k):
        return zones

    async def _devcoords(*a, **k):
        return device_coords

    monkeypatch.setattr(pipeline.context_client, "get_crop_context", _none, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_phenology_stages", _stages)
    monkeypatch.setattr(pipeline.context_client, "get_agri_crop", _crop, raising=False)
    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_coords", _coords, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_soil_properties", _soil, raising=False)
    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_geometry", _geom, raising=False)
    monkeypatch.setattr(pipeline, "_fetch_gdd", _gdd, raising=False)
    monkeypatch.setattr(pipeline, "get_phenology_params", _params, raising=False)
    monkeypatch.setattr(pipeline, "get_weather_snapshot", _weather, raising=False)
    monkeypatch.setattr(pipeline, "resolve_zones", _zones, raising=False)
    monkeypatch.setattr(pipeline, "_resolve_device_coords", _devcoords, raising=False)

    calls = []

    async def _fake_run(assessment, **kw):
        sensor = kw.get("redis_state") is not None
        calls.append({
            "zone_id": assessment.zone_id,
            "metric_type": kw.get("metric_type"),
            "sensor": sensor,
            "publish": kw.get("publish"),
        })
        assessment.overall_severity = Severity.HIGH if sensor else Severity.LOW
        return assessment

    published = []

    async def _pub(entity, tid):
        published.append(entity)
        return True

    monkeypatch.setattr(pipeline, "_run_engines", _fake_run, raising=False)
    monkeypatch.setattr(pipeline, "_publish_assessment", _pub, raising=False)
    monkeypatch.setattr(pipeline, "_emit_assessment_side_effects", _none, raising=False)
    return calls, published


@pytest.mark.asyncio
async def test_whole_parcel_unchanged_keeps_sensor_path(monkeypatch):
    calls, published = _patch_trigger(monkeypatch, zones=[Zone("parcel", _Z0)], device_coords=(5, 5))
    out = await pipeline.trigger(
        entity_id="urn:ngsi-ld:DeviceMeasurement:d1",
        metric_type=MetricType.LEAF_TEMPERATURE.value,
        redis_state=_Redis(),
        parcel_id="p1",
        tenant_id="t",
    )
    assert out is not None
    # exactly one engine run, with the sensor path, published via _run_engines (publish=True)
    assert len(calls) == 1
    assert calls[0]["sensor"] is True
    assert calls[0]["metric_type"] == MetricType.LEAF_TEMPERATURE.value
    assert calls[0]["publish"] is True


@pytest.mark.asyncio
async def test_zonal_attributes_sensor_to_device_zone(monkeypatch):
    zones = [Zone("z0", _Z0, urn="urn:ngsi-ld:AgriParcelZone:t:p1:z0"),
             Zone("z1", _Z1, urn="urn:ngsi-ld:AgriParcelZone:t:p1:z1")]
    # device sits in z0 (5,5)
    calls, published = _patch_trigger(monkeypatch, zones=zones, device_coords=(5, 5))
    out = await pipeline.trigger(
        entity_id="urn:ngsi-ld:DeviceMeasurement:d1",
        metric_type=MetricType.LEAF_TEMPERATURE.value,
        redis_state=_Redis(),
        parcel_id="p1",
        tenant_id="t",
    )
    by_zone = {c["zone_id"]: c for c in calls}
    assert by_zone["z0"]["sensor"] is True
    assert by_zone["z0"]["metric_type"] == MetricType.LEAF_TEMPERATURE.value
    assert by_zone["z1"]["sensor"] is False
    assert by_zone["z1"]["metric_type"] == ""
    types_pub = [e["type"] for e in published]
    assert types_pub.count("CropHealthZoneAssessment") == 2
    assert types_pub.count("CropHealthAssessment") == 1
    # rollup = worst zone (z0 sensor → HIGH)
    assert out.overall_severity == Severity.HIGH
    assert out.zone_id is None
