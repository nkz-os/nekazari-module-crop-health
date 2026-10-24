"""An under-panel sensor feeds only the under-panel index (and shade), never
parcel-level metrics from its own device history."""
from __future__ import annotations

import types

import pytest

from app.schemas import MetricType, SoilProperties
from app.services import pipeline
from app.services.parcel_link import OPEN_FIELD, UNDER_PANEL
from app.services.redis_state import ParcelReading
from app.services.zonation import Zone
from tests.test_pipeline_under_panel_stress import (
    _Z0, _Z1, NOW, PARCEL, FakeRedis, _setup, soil_reading,
)

DEVICE = "urn:ngsi-ld:DeviceMeasurement:d1"
SOIL = SoilProperties(has_data=True, hydraulics_from_soil=True, field_capacity=0.30, wilting_point=0.12)


class GateRedis(FakeRedis):
    """Context-aware parcel readings plus a per-device sliding window."""

    def __init__(self, by_context=None, window=None, **kw):
        super().__init__(**kw)
        self.by_context = by_context or {}
        self.window = window or {}

    async def get_parcel_readings(self, tenant, parcel, context, metric, max_age_s, now_ts):
        return [r for r in self.by_context.get((context, metric), []) if 0 <= now_ts - r.ts <= max_age_s]

    async def get_window(self, entity_id, metric, hours=1):
        return self.window.get(metric, [])


def _owner(monkeypatch, context):
    async def _o(device_id, tenant_id, redis_state):
        return PARCEL, context

    monkeypatch.setattr(pipeline, "_cached_device_owner", _o)


def _with_cwsi_params(monkeypatch):
    async def _params(*a, **k):
        return types.SimpleNamespace(
            stage="vegetative", kc=0.8, mds_ref=100.0, ky=0.45, d1=2.0, d2=-2.0)

    monkeypatch.setattr(pipeline, "get_phenology_params", _params, raising=False)


async def _run(metric, redis):
    return await pipeline.trigger(
        entity_id=DEVICE, metric_type=metric.value, redis_state=redis,
        parcel_id=None, tenant_id="tenant-a",
    )


@pytest.mark.asyncio
async def test_under_panel_soil_moisture_publishes_only_under_panel_index(monkeypatch):
    published, _ = _setup(monkeypatch, soil=SOIL, eppo="ZZZZZ")
    _owner(monkeypatch, UNDER_PANEL)
    redis = GateRedis(
        by_context={(UNDER_PANEL, "soilMoisture"): [soil_reading(16.0)]},
        window={"soilMoisture": [soil_reading(16.0)]},
    )
    out = await _run(MetricType.SOIL_MOISTURE, redis)
    assert out is not None
    a = published["assessments"][-1]
    e = a.to_ngsi_ld()
    assert a.soil_moisture_pct is None
    assert "soilMoisturePct" not in e
    assert e["underPanelWaterStressIndex"]["value"] == 0.556
    assert "waterStressFidelity" in e


@pytest.mark.asyncio
async def test_open_field_soil_moisture_behaves_as_before(monkeypatch):
    published, _ = _setup(monkeypatch, soil=SOIL, eppo="ZZZZZ")
    _owner(monkeypatch, OPEN_FIELD)
    redis = GateRedis(
        by_context={(OPEN_FIELD, "soilMoisture"): [soil_reading(17.0)]},
        window={"soilMoisture": [soil_reading(17.0)]},
    )
    await _run(MetricType.SOIL_MOISTURE, redis)
    e = published["assessments"][-1].to_ngsi_ld()
    assert e["soilMoisturePct"]["value"] == 17.0
    assert e["waterStressIndex"]["value"] == 0.444
    assert "underPanelWaterStressIndex" not in e


@pytest.mark.asyncio
async def test_under_panel_leaf_temperature_does_not_set_cwsi(monkeypatch):
    published, _ = _setup(monkeypatch, soil=SOIL)
    _with_cwsi_params(monkeypatch)
    _owner(monkeypatch, UNDER_PANEL)
    redis = GateRedis(window={"leafTemperature": [ParcelReading(DEVICE, NOW - 60, 30.0, "CEL")]})
    await _run(MetricType.LEAF_TEMPERATURE, redis)
    assert published["assessments"][-1].cwsi is None


@pytest.mark.asyncio
async def test_open_field_leaf_temperature_sets_cwsi(monkeypatch):
    published, _ = _setup(monkeypatch, soil=SOIL)
    _with_cwsi_params(monkeypatch)
    _owner(monkeypatch, OPEN_FIELD)
    redis = GateRedis(window={"leafTemperature": [ParcelReading(DEVICE, NOW - 60, 30.0, "CEL")]})
    await _run(MetricType.LEAF_TEMPERATURE, redis)
    assert published["assessments"][-1].cwsi is not None


@pytest.mark.asyncio
async def test_unresolvable_owner_skips_pipeline(monkeypatch):
    published, _ = _setup(monkeypatch, soil=SOIL)

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "_cached_device_owner", _none)
    assert await _run(MetricType.SOIL_MOISTURE, GateRedis()) is None
    assert published["assessments"] == []


@pytest.mark.asyncio
async def test_zonal_rollup_carries_under_panel_index(monkeypatch):
    published, _ = _setup(
        monkeypatch, soil=SOIL, eppo="ZZZZZ", zones=[Zone("z0", _Z0), Zone("z1", _Z1)])

    async def _nocoords(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "_resolve_device_coords", _nocoords, raising=False)
    _owner(monkeypatch, UNDER_PANEL)
    redis = GateRedis(by_context={(UNDER_PANEL, "soilMoisture"): [soil_reading(16.0)]})
    await _run(MetricType.SOIL_MOISTURE, redis)
    zone_ents = [e for e in published["entities"] if e["type"] == "CropHealthZoneAssessment"]
    parcel_ents = [e for e in published["entities"] if e["type"] == "CropHealthAssessment"]
    assert len(zone_ents) == 2 and len(parcel_ents) == 1
    for z in zone_ents:
        assert not any(k.startswith("underPanel") for k in z)
    p = parcel_ents[0]
    assert p["underPanelWaterStressIndex"]["value"] == 0.556
    assert p["underPanelWaterStressFidelity"]["value"] == "iot_sensor"


class CacheRedis:
    def __init__(self, cached=None):
        self.cached = cached
        self.set_calls = []

    async def get_json(self, key):
        return self.cached

    async def set_json(self, key, value, ttl):
        self.set_calls.append((key, value, ttl))


@pytest.mark.asyncio
async def test_cached_device_owner_hit_skips_broker(monkeypatch):
    async def _boom(*a, **k):
        raise AssertionError("broker must not be called on a cache hit")

    monkeypatch.setattr(pipeline, "_resolve_device_owner", _boom)
    r = CacheRedis({"parcel_id": "p-1", "context": UNDER_PANEL})
    assert await pipeline._cached_device_owner(DEVICE, "tenant-a", r) == ("p-1", UNDER_PANEL)
    assert r.set_calls == []


@pytest.mark.asyncio
async def test_cached_device_owner_miss_resolves_and_caches(monkeypatch):
    calls = []

    async def _res(device_id, tenant_id):
        calls.append((device_id, tenant_id))
        return "p-2", OPEN_FIELD

    monkeypatch.setattr(pipeline, "_resolve_device_owner", _res)
    r = CacheRedis(None)
    assert await pipeline._cached_device_owner(DEVICE, "tenant-a", r) == ("p-2", OPEN_FIELD)
    assert calls == [(DEVICE, "tenant-a")]
    assert r.set_calls == [
        (f"devowner:tenant-a:{DEVICE}", {"parcel_id": "p-2", "context": OPEN_FIELD},
         pipeline._DEVICE_PARCEL_TTL_S)
    ]
