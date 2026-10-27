"""Whole-parcel mode fetches nothing zonal; zonal mode fetches once per parcel; honest fidelity."""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

import pytest

from app.schemas import SoilProperties
from app.services import context_client, pipeline
from app.services.zone_inputs import gather_zone_inputs
from app.services.zonation import Zone

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
_SQ = {"type": "Polygon", "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]}


def _z(zid="z1", ver="v1", rank=1, **kw):
    return Zone(zone_id=zid, geometry=_SQ, zone_version=ver, zone_rank=rank, **kw)


async def _empty(*a, **k):
    return {}


async def _no_list(*a, **k):
    return []


# ── C4: whole-parcel mode ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gather_short_circuits_for_the_whole_parcel():
    called = []

    async def spy(*a, **k):
        called.append(1)
        return {}

    out = await gather_zone_inputs(
        "urn:p", "p1", "acme", [Zone("parcel", _SQ)], None, NOW,
        fetch_daily=spy, gather_sensors=spy, fetch_soil=spy, fetch_twi=spy,
    )
    assert out == {} and called == []


@pytest.mark.asyncio
async def test_whole_mode_compute_assessment_calls_no_zonal_endpoint(monkeypatch):
    from tests.test_compute_assessment_zonal import _patch_crop_level  # noqa: PLC0415

    _patch_crop_level(monkeypatch)
    called = []

    def spy(name):
        async def _f(*a, **k):
            called.append(name)
            return {} if name != "sensors" else [
                {"device_id": "d1", "lon": 1.0, "lat": 1.0, "readings": {"air_temp_c": 30.0}, "air_temp_c": 30.0}
            ]
        return _f

    async def _pub(entity, tid):
        return True

    async def _zones(pid, tid, geom):
        return [Zone("parcel", _SQ)]

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "_publish_assessment", _pub, raising=False)
    monkeypatch.setattr(pipeline, "resolve_zones", _zones, raising=False)
    monkeypatch.setattr(pipeline, "_clear_stale_water_stress", _noop)
    monkeypatch.setattr(pipeline, "_fetch_zone_daily", spy("daily"))
    monkeypatch.setattr(pipeline, "_gather_parcel_sensors", spy("sensors"))
    monkeypatch.setattr(context_client, "get_zone_soil", spy("soil"))
    monkeypatch.setattr(context_client, "get_zone_twi", spy("twi"))

    seen = {}
    real = pipeline._assess_zone

    async def _spy_zone(zone, *args, **kwargs):
        seen["sensor_ctx"] = args[4]
        seen["zone_ctx"] = kwargs.get("zone_ctx")
        return await real(zone, *args, **kwargs)

    monkeypatch.setattr(pipeline, "_assess_zone", _spy_zone)
    parcel_ctx = {"air_temp_c": 18.0}
    await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t", sensor_ctx=parcel_ctx)
    assert called == []
    assert seen["sensor_ctx"] == parcel_ctx
    assert seen["zone_ctx"] is None


# ── I2: time budget ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_zone_fetches_run_concurrently():
    started = asyncio.Event()
    count = 0

    def barrier(result):
        async def _f(*a, **k):
            nonlocal count
            count += 1
            if count == 4:
                started.set()
            await asyncio.wait_for(started.wait(), timeout=1.0)  # sequential calls would time out
            return result
        return _f

    out = await gather_zone_inputs(
        "urn:p", "p1", "acme", [_z()], None, NOW,
        fetch_daily=barrier({}), gather_sensors=barrier([]),
        fetch_soil=barrier({}), fetch_twi=barrier({}),
    )
    assert "z1" in out


@pytest.mark.asyncio
async def test_one_failing_fetch_does_not_sink_the_others():
    async def boom(*a, **k):
        raise RuntimeError("down")

    async def soil(p, t, zones):
        return {"z1": {"fidelity": "zone_specific", "horizon": {"fieldCapacity": 0.3, "wiltingPoint": 0.1}}}

    out = await gather_zone_inputs(
        "urn:p", "p1", "acme", [_z()], None, NOW,
        fetch_daily=boom, gather_sensors=boom, fetch_soil=soil, fetch_twi=boom,
    )
    assert out["z1"].soil["fieldCapacity"] == 0.3
    assert out["z1"].weather_daily == [] and out["z1"].twi is None


def _soil_ctx():
    return {"phenology": None, "soil": SoilProperties(field_capacity=0.27, wilting_point=0.12),
            "root_depth_mm": 600.0, "now": NOW}


class _Redis:
    def __init__(self):
        self.store = {}

    async def get_balance_state(self, tenant_id, parcel_id, zone_id=None):
        return self.store.get((zone_id,))

    async def set_balance_state(self, tenant_id, parcel_id, day, sw_mm, zone_id=None, **extras):
        self.store[(zone_id,)] = {"date": day, "sw_mm": sw_mm, **{k: v for k, v in extras.items() if v is not None}}
        return True

    async def try_lock(self, key, ttl_s):
        return True

    async def unlock(self, key):
        return None

    async def get_parcel_readings(self, *a, **k):
        return []


@pytest.mark.asyncio
async def test_one_series_fetch_per_parcel_for_many_zones(monkeypatch):
    daily_calls, irr_calls = [], []

    async def _daily(tenant_id, parcel_id, start, end):
        daily_calls.append((start, end))
        return {(start + timedelta(days=i)).isoformat(): (0.0, 3.0) for i in range((end - start).days + 1)}

    async def _irr(tenant_id, parcel_id, start, end):
        irr_calls.append((start, end))
        return {}

    monkeypatch.setattr(pipeline, "_fetch_daily_water", _daily)
    monkeypatch.setattr(pipeline, "_fetch_irrigation", _irr)
    zones = [_z(f"z{i}", ver=f"v{i}") for i in range(5)]
    from app.services.zone_inputs import ZoneInputs
    inputs = {z.zone_id: ZoneInputs(zone=z, weather={}, weather_daily=[], sensors={}, fidelity={}) for z in zones}
    out = await pipeline._scheduled_zone_balances(
        "urn:p", "p1", "acme", zones, inputs, _soil_ctx(),
        redis_state=_Redis(), depletion_p=0.5, now_ts=NOW.timestamp(),
    )
    assert len(out) == 5
    assert len(daily_calls) == 1 and len(irr_calls) == 1
    assert all(zi.fidelity["balance"] == "parcel_inherited" for zi in inputs.values())


@pytest.mark.asyncio
async def test_shared_series_refetches_the_union_for_an_earlier_start():
    calls = []

    async def fetch(tenant_id, parcel_id, start, end):
        calls.append((start, end))
        return {(start + timedelta(days=i)).isoformat(): i for i in range((end - start).days + 1)}

    shared = pipeline._SharedSeries(fetch)
    d = date(2026, 10, 20)
    a = await shared("t", "p", d, d + timedelta(days=2))
    b = await shared("t", "p", d + timedelta(days=1), d + timedelta(days=2))
    c = await shared("t", "p", d - timedelta(days=3), d + timedelta(days=2))
    assert calls == [(d, d + timedelta(days=2)), (d - timedelta(days=3), d + timedelta(days=2))]
    assert set(a) == {(d + timedelta(days=i)).isoformat() for i in range(3)}
    assert set(b) == {(d + timedelta(days=i)).isoformat() for i in (1, 2)}
    assert len(c) == 6


@pytest.mark.asyncio
async def test_shared_series_keeps_a_failure_for_the_range():
    calls = []

    async def fetch(*a):
        calls.append(a)
        return None

    shared = pipeline._SharedSeries(fetch)
    d = date(2026, 10, 20)
    assert await shared("t", "p", d, d) is None
    assert await shared("t", "p", d, d) is None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_no_balance_at_all_is_unavailable():
    zones = [_z()]
    out = await gather_zone_inputs(
        "urn:p", "p1", "acme", zones, None, NOW,
        fetch_daily=_empty, gather_sensors=_no_list, fetch_soil=_empty, fetch_twi=_empty,
    )
    assert out["z1"].fidelity["balance"] == "unavailable"
    res = await pipeline._scheduled_zone_balances(
        "urn:p", "p1", "acme", zones, out, _soil_ctx(), redis_state=None, depletion_p=0.5, now_ts=NOW.timestamp(),
    )
    assert res == {} and out["z1"].fidelity["balance"] == "unavailable"


# ── I3: fidelity precision ───────────────────────────────────────────────────

async def _gather(zone=None, daily=None, sensors=None, soil=None, twi=None, season=None):
    async def fd(*a, **k):
        return daily or {}

    async def gs(*a, **k):
        return sensors or []

    async def fs(*a, **k):
        return soil or {}

    async def ft(*a, **k):
        return twi or {}

    out = await gather_zone_inputs(
        "urn:p", "p1", "acme", [zone or _z()], season, NOW,
        fetch_daily=fd, gather_sensors=gs, fetch_soil=fs, fetch_twi=ft,
    )
    return out["z1"]


@pytest.mark.asyncio
async def test_meteo_is_iot_sensor_when_a_zone_sensor_gave_air_temperature():
    zone = _z(t_min=10.0, t_max=20.0, observed_at=NOW - timedelta(hours=1))
    sensor = {"device_id": "d1", "lon": 5.0, "lat": 5.0, "air_temp_c": 24.0, "readings": {"air_temp_c": 24.0}}
    assert (await _gather(zone, sensors=[sensor])).fidelity["meteo"] == "iot_sensor"
    assert (await _gather(zone)).fidelity["meteo"] == "zone_specific"
    humidity_only = {"device_id": "d2", "lon": 5.0, "lat": 5.0, "rh_pct": 50.0, "readings": {"rh_pct": 50.0}}
    assert (await _gather(zone, sensors=[humidity_only])).fidelity["meteo"] == "zone_specific"


@pytest.mark.asyncio
async def test_gdd_is_zone_specific_only_with_a_usable_row():
    unusable = {"z1": [{"date": "2026-10-01", "eto": 3.0}, {"date": "2026-10-02", "tMin": 5.0}]}
    assert (await _gather(daily=unusable)).fidelity["gdd"] == "parcel_inherited"
    usable = {"z1": [{"date": "2026-10-01", "eto": 3.0}, {"date": "2026-10-02", "tMin": 5.0, "tMax": 15.0}]}
    assert (await _gather(daily=usable)).fidelity["gdd"] == "zone_specific"


@pytest.mark.asyncio
async def test_soil_is_zone_specific_only_with_fc_and_wp():
    full = {"z1": {"fidelity": "zone_specific", "horizon": {"fieldCapacity": 0.3, "wiltingPoint": 0.1}}}
    lone = {"z1": {"fidelity": "zone_specific", "horizon": {"fieldCapacity": 0.3, "ksatSaturated": 5.0}}}
    assert (await _gather(soil=full)).fidelity["soil"] == "zone_specific"
    zi = await _gather(soil=lone)
    assert zi.fidelity["soil"] == "parcel_inherited"
    assert zi.soil["ksatSaturated"] == 5.0  # still usable, just not labelled zone-specific


@pytest.mark.asyncio
async def test_parcel_inherited_twi_writes_nothing_on_the_zone():
    twi = {"z1": {"fidelity": "parcel_inherited", "twiMean": 8.0, "wetFraction": 0.7}}
    zi = await _gather(twi=twi)
    assert zi.twi is None and zi.fidelity["twi"] == "parcel_inherited"
    za = pipeline.CropHealthAssessment(parcel_id="p1", assessed_at=NOW, zone_id="z1")
    entity = za.to_zone_ngsi_ld()
    assert "nkz:twiMean" not in entity and "nkz:wetnessClass" not in entity


# ── M2 / M3 / M4 ─────────────────────────────────────────────────────────────

class _Cache:
    def __init__(self):
        self.gets, self.sets = [], []

    async def get_json(self, key):
        self.gets.append(key)
        return None

    async def set_json(self, key, value, ttl_s):
        self.sets.append(key)
        return True


@pytest.mark.asyncio
async def test_no_cache_without_a_zone_version(monkeypatch):
    cache = _Cache()
    monkeypatch.setattr(context_client, "_zone_cache", lambda: cache)

    class _Resp:
        status_code = 200

        def json(self):
            return {"zones": [{"zoneId": "z1", "fidelity": "zone_specific", "horizon": {"fieldCapacity": 0.3}}]}

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return _Resp()

    monkeypatch.setattr(context_client.httpx, "AsyncClient", _Client)
    out = await context_client.get_zone_soil("urn:p", "acme", [_z(ver=None)], parcel_short="p1")
    assert "z1" in out and cache.gets == [] and cache.sets == []
    await context_client.get_zone_soil("urn:p", "acme", [_z(ver="v1")], parcel_short="p1")
    assert len(cache.gets) == 1 and len(cache.sets) == 1


def test_a_lone_zone_fc_or_wp_falls_back_to_the_parcel_pair():
    assert pipeline._zone_soil_values({"fieldCapacity": 0.4}) == (None, None)
    assert pipeline._zone_soil_values({"wiltingPoint": 0.2}) == (None, None)
    assert pipeline._zone_soil_values({"fieldCapacity": 0.4, "wiltingPoint": 0.2}) == (0.4, 0.2)
    parcel = SoilProperties(field_capacity=0.27, wilting_point=0.12)
    model = pipeline._zone_soil_model(parcel, {"fieldCapacity": 0.1})
    assert (model.field_capacity, model.wilting_point) == (0.27, 0.12)


@pytest.mark.asyncio
async def test_old_season_start_requests_the_last_400_days(caplog):
    seen = []

    async def fd(parcel, tenant, start, end):
        seen.append((start, end))
        return {}

    with caplog.at_level(logging.INFO, logger="app.services.zone_inputs"):
        await gather_zone_inputs(
            "urn:p", "p1", "acme", [_z()], "2024-01-05", NOW,
            fetch_daily=fd, gather_sensors=_no_list, fetch_soil=_empty, fetch_twi=_empty,
        )
    assert seen == [(NOW.date() - timedelta(days=400), NOW.date())]
    assert any("400" in r.getMessage() for r in caplog.records)
    seen.clear()
    await gather_zone_inputs(
        "urn:p", "p1", "acme", [_z()], "2026-09-01", NOW,
        fetch_daily=fd, gather_sensors=_no_list, fetch_soil=_empty, fetch_twi=_empty,
    )
    assert seen == [(date(2026, 9, 1), NOW.date())]
