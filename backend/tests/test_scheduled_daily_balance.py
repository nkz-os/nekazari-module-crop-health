"""The scheduled run steps the soil water balance once per closed day; triggers never do.

The real ``compute_assessment``/``trigger`` and the real stepper run; only I/O
(context clients, weather-api, Orion, Redis) is faked.
"""
from datetime import date, timedelta

import pytest

from app.services import pipeline
from tests.test_pipeline_under_panel_stress import (
    PARCEL, YESTERDAY, FakeRedis, _setup, _trigger, soil_reading,
)

TENANT = "tenant-a"
URN = f"urn:ngsi-ld:AgriParcel:{PARCEL}"
YDAY = date.fromisoformat(YESTERDAY)


def _fetch_full(precip=1.0, et0=3.0):
    calls = []

    async def fetch(tenant_id, parcel_id, start, end):
        calls.append((tenant_id, parcel_id, start, end))
        out = {}
        d = start
        while d <= end:
            out[d.isoformat()] = (precip, et0)
            d += timedelta(days=1)
        return out

    fetch.calls = calls
    return fetch


def _irrigation(data=None):
    calls = []

    async def fetch_irrigation(tenant_id, parcel_id, start, end):
        calls.append((tenant_id, parcel_id, start, end))
        return dict(data or {})

    fetch_irrigation.calls = calls
    return fetch_irrigation


def _setup_scheduled(monkeypatch, redis, *, redis_error=False, fetch=None, irrigation=None):
    published, _ = _setup(monkeypatch)

    async def _crop(parcel_id, tenant_id):
        return {"species": "OLVEU", "plantingDate": None, "variety": None}

    async def _none(*a, **k):
        return None

    async def _no_sensors(*a, **k):
        return []

    def _get_redis_state():
        if redis_error:
            raise RuntimeError("Redis not initialised")
        return redis

    fetch = fetch or _fetch_full()
    monkeypatch.setattr(pipeline, "_read_assigned_crop", _crop)
    monkeypatch.setattr(pipeline, "_gather_parcel_sensors", _no_sensors)
    monkeypatch.setattr(pipeline, "_fetch_daily_water", fetch)
    monkeypatch.setattr(pipeline, "_fetch_irrigation", irrigation or _irrigation())
    monkeypatch.setattr("app.main.get_redis_state", _get_redis_state)
    return published, fetch


def _rollup_entity(published):
    return [e for e in published["entities"] if e["type"] == "CropHealthAssessment"][-1]


@pytest.mark.asyncio
async def test_scheduled_run_steps_and_saves(monkeypatch):
    redis = FakeRedis()
    published, fetch = _setup_scheduled(monkeypatch, redis)
    out = await pipeline.compute_assessment(URN, TENANT)
    assert fetch.calls == [(TENANT, PARCEL, YDAY - timedelta(days=29), YDAY)]
    assert len(redis.saved) == 1
    parcel, day, sw = redis.saved[0]
    assert (parcel, day) == (PARCEL, YESTERDAY)
    assert out.soil_water_balance.sw_mm == sw
    # Kc from phenology (0.8) x ET0 (3.0) on the last stepped day.
    assert out.water_balance.etc_mm == pytest.approx(2.4)
    assert out.water_balance.precip_mm == pytest.approx(1.0)
    # The saved state keeps that day's flows for the read-only runs.
    assert (redis.state["precip_mm"], redis.state["etc_mm"]) == (pytest.approx(1.0), pytest.approx(2.4))


@pytest.mark.asyncio
async def test_scheduled_run_publishes_water_stress(monkeypatch):
    published, _ = _setup_scheduled(monkeypatch, FakeRedis())
    await pipeline.compute_assessment(URN, TENANT)
    e = _rollup_entity(published)
    assert e["waterStressFidelity"]["value"] == "parcel_weather"
    assert "waterStressIndex" in e


@pytest.mark.asyncio
async def test_scheduled_run_with_current_state_does_not_fetch(monkeypatch):
    redis = FakeRedis(state={"date": YESTERDAY, "sw_mm": 40.0})
    _, fetch = _setup_scheduled(monkeypatch, redis)
    out = await pipeline.compute_assessment(URN, TENANT)
    assert fetch.calls == []
    assert redis.saved == []
    assert out.soil_water_balance.sw_mm == 40.0
    assert out.water_balance is None  # no stored flows: no 0 mm published as real


@pytest.mark.asyncio
async def test_scheduled_run_with_current_state_reports_its_stored_flows(monkeypatch):
    redis = FakeRedis(state={
        "date": YESTERDAY, "sw_mm": 40.0,
        "precip_mm": 3.0, "etc_mm": 2.4, "actual_et_mm": 2.4, "deep_percolation_mm": 0.0,
    })
    _, fetch = _setup_scheduled(monkeypatch, redis)
    out = await pipeline.compute_assessment(URN, TENANT)
    assert fetch.calls == []
    assert (out.water_balance.precip_mm, out.water_balance.etc_mm) == (3.0, 2.4)


@pytest.mark.asyncio
async def test_scheduled_run_corrects_with_open_field_probe(monkeypatch):
    redis = FakeRedis(
        state={"date": YESTERDAY, "sw_mm": 40.0},
        readings={"soilMoisture": [soil_reading(20.0)]},
    )
    _setup_scheduled(monkeypatch, redis)
    out = await pipeline.compute_assessment(URN, TENANT)
    swb = out.soil_water_balance
    expected = min(max((0.20 - 0.12) * swb.root_depth_mm, 0.0), swb.awc_mm)
    assert redis.saved == [(PARCEL, YESTERDAY, pytest.approx(expected))]
    assert swb.sw_mm == pytest.approx(expected, abs=0.01)


@pytest.mark.asyncio
async def test_triggers_do_not_step(monkeypatch):
    redis = FakeRedis(state={"date": YESTERDAY, "sw_mm": 40.0})
    published, fetch = _setup_scheduled(monkeypatch, redis)
    for _ in range(3):
        await _trigger(redis)
    assert fetch.calls == []
    assert redis.saved == []
    assert redis.state == {"date": YESTERDAY, "sw_mm": 40.0}
    assert [a.soil_water_balance.sw_mm for a in published["assessments"]] == [40.0] * 3


@pytest.mark.asyncio
async def test_triggers_with_probes_never_write_the_balance(monkeypatch):
    redis = FakeRedis(
        state={"date": YESTERDAY, "sw_mm": 40.0},
        readings={"soilMoisture": [soil_reading(20.0)]},
    )
    _, fetch = _setup_scheduled(monkeypatch, redis)
    for _ in range(3):
        await _trigger(redis)
    assert fetch.calls == []
    assert redis.saved == []
    assert redis.state == {"date": YESTERDAY, "sw_mm": 40.0}


@pytest.mark.asyncio
async def test_scheduled_correction_keeps_the_step_excess_and_flows(monkeypatch):
    # A wet spin-up (heavy rain every day) ends in percolation; the probe then corrects the water.
    redis = FakeRedis(readings={"soilMoisture": [soil_reading(20.0)]})
    _setup_scheduled(monkeypatch, redis, fetch=_fetch_full(precip=30.0, et0=3.0))
    out = await pipeline.compute_assessment(URN, TENANT)
    swb = out.soil_water_balance
    assert len(redis.saved) == 2  # the step, then the correction (same date)
    step_sw, corrected_sw = redis.saved[0][2], redis.saved[1][2]
    assert redis.saved[0][1] == redis.saved[1][1] == YESTERDAY
    assert corrected_sw < step_sw
    assert swb.sw_mm == pytest.approx(corrected_sw, abs=0.01)
    assert swb.excess_mm > 0
    assert swb.excess_mm == redis.state["deep_percolation_mm"]
    assert redis.state["root_depth_mm"] == swb.root_depth_mm
    assert out.waterlogging_risk is not None
    assert (out.water_balance.precip_mm, out.water_balance.etc_mm) == (30.0, pytest.approx(2.4))


@pytest.mark.asyncio
async def test_trigger_with_lagging_state_reports_low_confidence(monkeypatch):
    lagging = (YDAY - timedelta(days=3)).isoformat()
    redis = FakeRedis(state={"date": lagging, "sw_mm": 40.0})
    published, _ = _setup_scheduled(monkeypatch, redis)
    await _trigger(redis)
    swb = published["assessments"][-1].soil_water_balance
    assert swb.sw_mm == 40.0
    assert swb.soil_moisture_confidence == "low"


@pytest.mark.asyncio
async def test_trigger_ignores_state_older_than_replay_window(monkeypatch):
    old = (YDAY - timedelta(days=31)).isoformat()
    published, _ = _setup_scheduled(monkeypatch, FakeRedis())
    await _trigger(FakeRedis(state={"date": old, "sw_mm": 40.0}))
    a = published["assessments"][-1]
    assert a.soil_water_balance is None
    assert a.water_balance is None


@pytest.mark.asyncio
async def test_redis_unavailable_scheduled_run_still_publishes(monkeypatch):
    published, fetch = _setup_scheduled(monkeypatch, None, redis_error=True)
    out = await pipeline.compute_assessment(URN, TENANT)
    assert out is not None
    assert out.soil_water_balance is None
    assert fetch.calls == []
    e = _rollup_entity(published)
    assert e["waterStressFidelity"]["value"] == "unavailable"
    assert "waterStressIndex" not in e


@pytest.mark.asyncio
async def test_scheduled_run_passes_irrigation(monkeypatch):
    dry = FakeRedis()
    _setup_scheduled(monkeypatch, dry)
    await pipeline.compute_assessment(URN, TENANT)
    wet = FakeRedis()
    irrigation = _irrigation({YESTERDAY: 5.0})
    _setup_scheduled(monkeypatch, wet, irrigation=irrigation)
    await pipeline.compute_assessment(URN, TENANT)
    assert irrigation.calls == [(TENANT, PARCEL, YDAY - timedelta(days=29), YDAY)]
    assert wet.state["sw_mm"] == pytest.approx(dry.state["sw_mm"] + 5.0, abs=0.01)
    assert wet.state["anchor_date"] == (YDAY - timedelta(days=7)).isoformat()


@pytest.mark.asyncio
async def test_scheduled_run_never_calls_bioorch_fertilizer_and_emits_no_npk(monkeypatch):
    import httpx

    urls = []

    class _RecordingClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, *a, **k):
            urls.append(str(url))
            raise RuntimeError("no network in tests")

    published, _ = _setup_scheduled(monkeypatch, FakeRedis())
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)
    out = await pipeline.compute_assessment(URN, TENANT)
    assert out.crop_requirements is not None
    assert not any("/recommendations/fertilizer" in u for u in urls)
    e = _rollup_entity(published)
    for attr in ("nRequirementKgHa", "p2o5RequirementKgHa", "k2oRequirementKgHa"):
        assert attr not in e
