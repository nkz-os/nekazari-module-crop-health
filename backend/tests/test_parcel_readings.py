"""Per-parcel readings and the daily shade accumulator."""
import json
import logging
import time
from datetime import datetime, timezone

import pytest

from app.services import pipeline
from app.services.redis_state import ParcelReading, RedisState

TENANT = "tenant-a"
PARCEL = "p-1"
DEVICE = "urn:ngsi-ld:Device:tenant-a:par-1"


class FakeRedis:
    """In-memory stub of the Redis calls RedisState uses."""

    def __init__(self):
        self.kv = {}
        self.hashes = {}
        self.ttl = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None, nx=False):
        self.kv[k] = v
        self.ttl[k] = ex
        return True

    async def hset(self, k, field, value):
        self.hashes.setdefault(k, {})[field] = value

    async def hgetall(self, k):
        return dict(self.hashes.get(k, {}))

    async def hincrbyfloat(self, k, field, amount):
        h = self.hashes.setdefault(k, {})
        h[field] = str(float(h.get(field, 0)) + amount)

    async def hget(self, k, field):
        return self.hashes.get(k, {}).get(field)

    async def expire(self, k, seconds):
        self.ttl[k] = seconds

    def pipeline(self, transaction=True):
        return _FakePipe(self)


class _FakePipe:
    def __init__(self, client):
        self.client = client
        self.ops = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def hincrbyfloat(self, k, field, amount):
        self.ops.append(self.client.hincrbyfloat(k, field, amount))

    def hset(self, k, field, value):
        self.ops.append(self.client.hset(k, field, value))

    def expire(self, k, seconds):
        self.ops.append(self.client.expire(k, seconds))

    async def execute(self):
        for op in self.ops:
            await op


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def state():
    return RedisState(client=FakeRedis())


NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc).timestamp()


@pytest.mark.anyio
async def test_parcel_readings_drop_stale_and_future(state):
    await state.set_parcel_reading(TENANT, PARCEL, "open_field", "soilMoisture", "d-fresh", NOW - 100, 30.0, "P1")
    await state.set_parcel_reading(TENANT, PARCEL, "open_field", "soilMoisture", "d-stale", NOW - 4000, 31.0, "P1")
    await state.set_parcel_reading(TENANT, PARCEL, "open_field", "soilMoisture", "d-future", NOW + 900, 32.0, None)
    got = await state.get_parcel_readings(TENANT, PARCEL, "open_field", "soilMoisture", 3600, NOW)
    assert got == [ParcelReading("d-fresh", NOW - 100, 30.0, "P1")]
    assert state._client.ttl[f"{state._prefix}parcel:{TENANT}:{PARCEL}:open_field:soilMoisture"] == 7200


@pytest.mark.anyio
async def test_older_out_of_order_reading_does_not_overwrite_newer(state):
    await state.set_parcel_reading(TENANT, PARCEL, "open_field", "soilMoisture", "d", NOW - 10, 30.0, "P1")
    await state.set_parcel_reading(TENANT, PARCEL, "open_field", "soilMoisture", "d", NOW - 500, 99.0, "P1")
    got = await state.get_parcel_readings(TENANT, PARCEL, "open_field", "soilMoisture", 3600, NOW)
    assert got == [ParcelReading("d", NOW - 10, 30.0, "P1")]
    await state.set_parcel_reading(TENANT, PARCEL, "open_field", "soilMoisture", "d", NOW - 5, 31.0, "P1")
    got = await state.get_parcel_readings(TENANT, PARCEL, "open_field", "soilMoisture", 3600, NOW)
    assert got[0].value == 31.0


@pytest.mark.anyio
async def test_daily_shade_is_one_minus_under_over_open(state):
    await state.add_shade_sample(TENANT, PARCEL, "2026-06-15", 400, 1600)
    await state.add_shade_sample(TENANT, PARCEL, "2026-06-15", 200, 1800)
    assert await state.get_daily_shade(TENANT, PARCEL, "2026-06-15") == pytest.approx(1 - 600 / 3400)
    assert state._client.ttl[f"{state._prefix}shade:{TENANT}:{PARCEL}:2026-06-15"] == 3 * 86400


@pytest.mark.anyio
async def test_daily_shade_none_without_open_light(state):
    assert await state.get_daily_shade(TENANT, PARCEL, "2026-06-15") is None


@pytest.mark.anyio
async def test_daily_shade_clamped(state):
    await state.add_shade_sample(TENANT, PARCEL, "d", 3000, 1000)
    assert await state.get_daily_shade(TENANT, PARCEL, "d") == 0.0


@pytest.mark.anyio
async def test_record_unlinked_device_returns_none_and_logs_once(state, monkeypatch, caplog):
    async def _none(device_id, tenant_id):
        return None

    monkeypatch.setattr(pipeline, "_resolve_device_owner", _none)
    with caplog.at_level(logging.WARNING):
        out = await pipeline.record_parcel_reading(
            DEVICE, "photosyntheticPhotonFluxDensity", NOW, 400.0, None, TENANT, state
        )
    assert out is None
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def _patch(monkeypatch, ghi, obs_ts=NOW):
    monkeypatch.setattr(pipeline, "_now_ts", lambda: NOW)
    calls = {"resolve": 0, "meteo": 0}

    async def _resolve(device_id, tenant_id):
        calls["resolve"] += 1
        return PARCEL, "open_field"

    async def _meteo(parcel_id, tenant_id):
        calls["meteo"] += 1
        if ghi is None:
            return {}
        out = {"solar_radiation_wm2": ghi}
        if obs_ts is not None:
            out["observed_at_ts"] = obs_ts
        return out

    monkeypatch.setattr(pipeline, "_resolve_device_owner", _resolve)
    monkeypatch.setattr(pipeline, "_regional_meteo", _meteo)
    return calls


@pytest.mark.anyio
async def test_par_with_daylight_adds_shade_sample_on_utc_day(state, monkeypatch):
    _patch(monkeypatch, 800.0)
    out = await pipeline.record_parcel_reading(
        DEVICE, "photosyntheticPhotonFluxDensity", NOW, 808.0, None, TENANT, state
    )
    assert out == PARCEL
    assert await state.get_daily_shade(TENANT, PARCEL, "2026-06-15") == pytest.approx(1 - 808 / (2.02 * 800))


@pytest.mark.anyio
async def test_par_at_night_adds_no_shade_sample(state, monkeypatch):
    _patch(monkeypatch, 20.0)
    await pipeline.record_parcel_reading(
        DEVICE, "photosyntheticPhotonFluxDensity", NOW, 5.0, None, TENANT, state
    )
    assert await state.get_daily_shade(TENANT, PARCEL, "2026-06-15") is None


@pytest.mark.anyio
async def test_par_without_ghi_adds_no_shade_sample(state, monkeypatch):
    _patch(monkeypatch, None)
    await pipeline.record_parcel_reading(
        DEVICE, "photosyntheticPhotonFluxDensity", NOW, 500.0, None, TENANT, state
    )
    assert await state.get_daily_shade(TENANT, PARCEL, "2026-06-15") is None


@pytest.mark.anyio
async def test_ghi_cached_300s_and_device_parcel_cached(state, monkeypatch):
    calls = _patch(monkeypatch, 800.0)
    for _ in range(2):
        await pipeline.record_parcel_reading(
            DEVICE, "photosyntheticPhotonFluxDensity", NOW, 400.0, None, TENANT, state
        )
    assert calls == {"resolve": 1, "meteo": 1}
    assert 300 in state._client.ttl.values()


@pytest.mark.anyio
async def test_non_par_metric_stores_reading_without_meteo(state, monkeypatch):
    calls = _patch(monkeypatch, 800.0)
    await pipeline.record_parcel_reading(DEVICE, "soilMoisture", NOW, 30.0, "P1", TENANT, state)
    assert calls["meteo"] == 0
    got = await state.get_parcel_readings(TENANT, PARCEL, "open_field", "soilMoisture", 3600, NOW)
    assert got[0].unit_code == "P1"


PAR = "photosyntheticPhotonFluxDensity"


@pytest.mark.anyio
@pytest.mark.parametrize("ghi", [float("inf"), float("nan")])
async def test_non_finite_ghi_adds_no_shade_sample(state, monkeypatch, ghi):
    _patch(monkeypatch, ghi)
    await pipeline.record_parcel_reading(DEVICE, PAR, NOW, 400.0, None, TENANT, state)
    assert await state.get_daily_shade(TENANT, PARCEL, "2026-06-15") is None


@pytest.mark.anyio
@pytest.mark.parametrize("ts", [NOW + 400, NOW - 3700])
async def test_delayed_or_future_par_adds_no_shade_sample(state, monkeypatch, ts):
    _patch(monkeypatch, 800.0)
    out = await pipeline.record_parcel_reading(DEVICE, PAR, ts, 400.0, None, TENANT, state)
    assert out == PARCEL
    day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    assert await state.get_daily_shade(TENANT, PARCEL, day) is None
    assert await state.get_daily_shade(TENANT, PARCEL, "2026-06-15") is None


@pytest.mark.anyio
async def test_absurd_timestamp_returns_none_and_does_not_raise(state, monkeypatch):
    _patch(monkeypatch, 800.0, obs_ts=1e15)
    # clock and ts both absurd (ms epoch): passes the age check, fails in fromtimestamp
    monkeypatch.setattr(pipeline, "_now_ts", lambda: 1e15)
    out = await pipeline.record_parcel_reading(DEVICE, PAR, 1e15, 400.0, None, TENANT, state)
    assert out is None


@pytest.mark.anyio
async def test_resolver_error_does_not_raise(state, monkeypatch):
    async def _boom(device_id, tenant_id):
        raise RuntimeError("broker down")

    monkeypatch.setattr(pipeline, "_resolve_device_owner", _boom)
    assert await pipeline.record_parcel_reading(DEVICE, PAR, NOW, 1.0, None, TENANT, state) is None


@pytest.mark.anyio
async def test_future_stamped_reading_not_stored_and_later_valid_one_is(state):
    now = time.time()
    await state.set_parcel_reading(TENANT, PARCEL, "open_field", "soilMoisture", "d", now + 1e6, 99.0, "P1")
    assert state._client.hashes == {}
    await state.set_parcel_reading(TENANT, PARCEL, "open_field", "soilMoisture", "d", now - 10, 30.0, "P1")
    got = await state.get_parcel_readings(TENANT, PARCEL, "open_field", "soilMoisture", 3600, now)
    assert [r.value for r in got] == [30.0]


@pytest.mark.anyio
async def test_poisoned_stored_entry_is_replaced_by_valid_reading(state):
    now = time.time()
    key = f"{state._prefix}parcel:{TENANT}:{PARCEL}:open_field:soilMoisture"
    state._client.hashes[key] = {"d": json.dumps({"ts": now + 1e6, "v": 99.0, "u": "P1"})}
    await state.set_parcel_reading(TENANT, PARCEL, "open_field", "soilMoisture", "d", now - 10, 30.0, "P1")
    got = await state.get_parcel_readings(TENANT, PARCEL, "open_field", "soilMoisture", 3600, now)
    assert [r.value for r in got] == [30.0]
    assert state._client.ttl[key] == 7200


@pytest.mark.anyio
async def test_stale_ghi_adds_no_shade_sample(state, monkeypatch):
    _patch(monkeypatch, 800.0, obs_ts=NOW - 2 * 3600)
    await pipeline.record_parcel_reading(DEVICE, PAR, NOW, 400.0, None, TENANT, state)
    assert await state.get_daily_shade(TENANT, PARCEL, "2026-06-15") is None


@pytest.mark.anyio
async def test_ghi_without_observation_time_adds_no_shade_sample(state, monkeypatch):
    _patch(monkeypatch, 800.0, obs_ts=None)
    await pipeline.record_parcel_reading(DEVICE, PAR, NOW, 400.0, None, TENANT, state)
    assert await state.get_daily_shade(TENANT, PARCEL, "2026-06-15") is None


@pytest.mark.anyio
async def test_fresh_ghi_within_90_min_adds_sample(state, monkeypatch):
    _patch(monkeypatch, 800.0, obs_ts=NOW - 80 * 60)
    await pipeline.record_parcel_reading(DEVICE, PAR, NOW, 400.0, None, TENANT, state)
    assert await state.get_daily_shade(TENANT, PARCEL, "2026-06-15") is not None


@pytest.mark.anyio
@pytest.mark.parametrize("par", [-1.0, 3001.0, float("nan"), float("inf")])
async def test_implausible_par_adds_no_shade_sample(state, monkeypatch, par, caplog):
    _patch(monkeypatch, 800.0)
    with caplog.at_level(logging.WARNING):
        await pipeline.record_parcel_reading(DEVICE, PAR, NOW, par, None, TENANT, state)
    assert await state.get_daily_shade(TENANT, PARCEL, "2026-06-15") is None
    assert any("PAR" in r.getMessage() for r in caplog.records)


@pytest.mark.anyio
async def test_shade_sample_records_latest_par_ts(state, monkeypatch):
    _patch(monkeypatch, 800.0)
    await pipeline.record_parcel_reading(DEVICE, PAR, NOW - 60, 400.0, None, TENANT, state)
    await pipeline.record_parcel_reading(DEVICE, PAR, NOW - 10, 400.0, None, TENANT, state)
    await pipeline.record_parcel_reading(DEVICE, PAR, NOW - 300, 400.0, None, TENANT, state)
    assert await state.get_daily_shade_ts(TENANT, PARCEL, "2026-06-15") == NOW - 10
    assert await state.get_daily_shade_ts(TENANT, PARCEL, "2026-06-14") is None


@pytest.mark.anyio
async def test_regional_meteo_returns_observation_time(monkeypatch):
    payload = [{"solarRadiation": 700, "dateObserved": "2026-06-15T11:30:00Z"}]

    class _Resp:
        status_code = 200

        def json(self):
            return payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, *a, **k):
            return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Client())
    out = await pipeline._regional_meteo("p-1", TENANT)
    assert out["solar_radiation_wm2"] == 700.0
    assert out["observed_at_ts"] == datetime(2026, 6, 15, 11, 30, tzinfo=timezone.utc).timestamp()
