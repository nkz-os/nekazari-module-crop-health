"""Shade pairs park PAR with the parcel pyranometer; the park never supplies GHI."""
from datetime import datetime, timezone

import pytest

from app.engines.under_panel_stress import PAR_PER_GHI
from app.services import pipeline
from app.services.redis_state import RedisState
from tests.test_parcel_readings import FakeRedis

TENANT = "tenant-a"
PARCEL = "p-1"
PAR = "photosyntheticPhotonFluxDensity"
SOLAR = "solarRadiation"
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc).timestamp()
DAY = "2026-06-15"

OWNERS = {
    "par-a": (PARCEL, "under_panel"),
    "par-b": (PARCEL, "under_panel"),
    "par-open": (PARCEL, "open_field"),
    "pyr-open": (PARCEL, "open_field"),
    "pyr-park": (PARCEL, "under_panel"),
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def state():
    return RedisState(client=FakeRedis())


def _patch(monkeypatch, wo_ghi=None, wo_ts=NOW):
    monkeypatch.setattr(pipeline, "_now_ts", lambda: NOW)

    async def _resolve(device_id, tenant_id):
        return OWNERS[device_id]

    async def _meteo(parcel_id, tenant_id):
        if wo_ghi is None:
            return {}
        return {"solar_radiation_wm2": wo_ghi, "observed_at_ts": wo_ts}

    monkeypatch.setattr(pipeline, "_resolve_device_owner", _resolve)
    monkeypatch.setattr(pipeline, "_regional_meteo", _meteo)


async def _rec(state, device, metric, value, ts=NOW, unit=None):
    return await pipeline.record_parcel_reading(device, metric, ts, value, unit, TENANT, state)


@pytest.mark.anyio
async def test_two_park_sensors_pool_into_daily_shade(state, monkeypatch):
    _patch(monkeypatch, wo_ghi=700.0)
    await _rec(state, "par-a", PAR, 0.0)
    await _rec(state, "par-b", PAR, PAR_PER_GHI * 700)
    assert await state.get_daily_shade(TENANT, PARCEL, DAY) == pytest.approx(0.5)


@pytest.mark.anyio
async def test_park_par_pairs_with_parcel_pyranometer(state, monkeypatch):
    _patch(monkeypatch, wo_ghi=100.0)
    await _rec(state, "pyr-open", SOLAR, 700.0, unit="D54")
    await _rec(state, "par-a", PAR, 900.0)
    sums = state._client.hashes[f"{state._prefix}shade:{TENANT}:{PARCEL}:{DAY}"]
    assert float(sums["under"]) == pytest.approx(900.0)
    assert float(sums["open"]) == pytest.approx(PAR_PER_GHI * 700)


@pytest.mark.anyio
async def test_open_field_par_adds_no_shade_sample(state, monkeypatch):
    _patch(monkeypatch, wo_ghi=700.0)
    await _rec(state, "par-open", PAR, 900.0)
    assert await state.get_daily_shade(TENANT, PARCEL, DAY) is None


@pytest.mark.anyio
async def test_park_pyranometer_never_becomes_ghi(state, monkeypatch):
    _patch(monkeypatch, wo_ghi=700.0)
    await _rec(state, "pyr-park", SOLAR, 1000.0, unit="D54")
    assert await pipeline._cached_ghi(PARCEL, TENANT, state) == (700.0, NOW)
    got = await state.get_parcel_readings(TENANT, PARCEL, "under_panel", SOLAR, 3600, NOW)
    assert got == []


@pytest.mark.anyio
async def test_parcel_pyranometer_wins_over_cached_weather_observed(state, monkeypatch):
    _patch(monkeypatch, wo_ghi=700.0)
    assert await pipeline._cached_ghi(PARCEL, TENANT, state) == (700.0, NOW)  # fills the cache
    await _rec(state, "pyr-open", SOLAR, 650.0, ts=NOW - 60, unit="D54")
    assert await pipeline._cached_ghi(PARCEL, TENANT, state) == (650.0, NOW - 60)


@pytest.mark.anyio
async def test_pyranometer_with_unit_none_is_accepted(state, monkeypatch):
    _patch(monkeypatch, wo_ghi=700.0)
    await _rec(state, "pyr-open", SOLAR, 650.0, unit=None)
    assert await pipeline._cached_ghi(PARCEL, TENANT, state) == (650.0, NOW)


@pytest.mark.anyio
async def test_pyranometer_with_wrong_unit_is_ignored(state, monkeypatch):
    _patch(monkeypatch, wo_ghi=700.0)
    await _rec(state, "pyr-open", SOLAR, 650.0, unit="W27")
    assert await pipeline._cached_ghi(PARCEL, TENANT, state) == (700.0, NOW)


@pytest.mark.anyio
async def test_stale_pyranometer_falls_back_to_weather_observed(state, monkeypatch):
    _patch(monkeypatch, wo_ghi=700.0)
    await _rec(state, "pyr-open", SOLAR, 650.0, ts=NOW - pipeline._GHI_MAX_SKEW_S - 60, unit="D54")
    assert await pipeline._cached_ghi(PARCEL, TENANT, state) == (700.0, NOW)
