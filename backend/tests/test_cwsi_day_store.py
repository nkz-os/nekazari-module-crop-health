"""The day's sensor CWSI: kept per parcel (and zone) per local solar day, never carried over."""
from __future__ import annotations

import types
from datetime import date, datetime, timedelta, timezone

import pytest

from app.schemas import CropHealthAssessment, CWSIResult, CwsiBaseline, MetricType, WaterStressReference
from app.services import pipeline
from app.services.parcel_link import OPEN_FIELD
from app.services.redis_state import ParcelReading, StoreError
from tests.test_pipeline_under_panel_stress import NOW, STATE, _setup
from tests.test_under_panel_sensor_gating import DEVICE, SOIL, GateRedis, _owner, _run
from tests.test_post_maturity import _no_network, _offline_context  # noqa: F401  (autouse: offline)


class DayRedis(GateRedis):
    """GateRedis plus an in-memory JSON store (records TTLs)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.json: dict = {}
        self.ttl: dict = {}

    async def get_json(self, key):
        return self.json.get(key)

    async def set_json(self, key, value, ttl_s):
        self.json[key] = value
        self.ttl[key] = ttl_s
        return True


def _ref():
    # clearSky false: this module is about the day store, not the sky check.
    return WaterStressReference(baselines=[CwsiBaseline.model_validate({
        "id": "b", "a0C": 3.38, "a1CPerKpa": -3.25,
        "upper": {"form": "constant", "valueC": 1.0},
        "valid": {"solarHourFrom": 10, "solarHourTo": 16, "clearSky": False},
    })])


def _wire(monkeypatch, at_ts, *, lon=0.0):
    published, _ = _setup(
        monkeypatch, soil=SOIL, wm={},
        regional={"air_temp_c": 35.0, "rh_pct": 20.0, "et0_mm": 5.0, "observed_at_ts": at_ts - 600},
    )

    async def _params(*a, **k):
        return types.SimpleNamespace(
            stage="vegetative", kc=0.8, mds_ref=100.0, ky=0.45, d1=None, d2=None,
            species="OLVEU", water_stress_reference=_ref())

    async def _coords(*a, **k):
        return (40.0, lon)

    monkeypatch.setattr(pipeline, "get_phenology_params", _params, raising=False)
    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_coords", _coords, raising=False)
    monkeypatch.setattr(pipeline, "_now_ts", lambda: at_ts)
    _owner(monkeypatch, OPEN_FIELD)
    return published


@pytest.mark.asyncio
async def test_day_cwsi_survives_a_later_webhook_and_not_the_next_day(monkeypatch):
    redis = DayRedis(
        window={"leafTemperature": [ParcelReading(DEVICE, NOW - 60, 38.0, "CEL")]},
        state=dict(STATE),
    )
    # 12:00 UTC at longitude 0 = solar noon: leaf reading -> high CWSI.
    published = _wire(monkeypatch, NOW)
    await _run(MetricType.LEAF_TEMPERATURE, redis)
    first = published["assessments"][-1]
    assert first.water_stress_indicator.method == "cwsi_sensor"
    assert first.water_stress_indicator.level == "high"

    # 15:00 the same day: a soil-moisture webhook keeps the day's CWSI level.
    later = _wire(monkeypatch, NOW + 3 * 3600)
    redis.window = {}
    await _run(MetricType.SOIL_MOISTURE, redis)
    a = later["assessments"][-1]
    assert a.cwsi is not None and a.cwsi.cwsi == first.cwsi.cwsi
    assert a.water_stress_indicator.method == "cwsi_sensor"
    assert a.water_stress_indicator.level == "high"
    e = a.to_ngsi_ld()
    assert e["cwsiValue"]["value"] == first.cwsi.cwsi
    assert e["waterStressMethod"]["value"] == "cwsi_sensor"

    # Next day: nothing carries over, the balance decides.
    nxt = _wire(monkeypatch, NOW + 24 * 3600)
    await _run(MetricType.SOIL_MOISTURE, redis)
    b = nxt["assessments"][-1]
    assert b.cwsi is None
    assert b.water_stress_indicator.method == "balance"


@pytest.mark.asyncio
async def test_day_store_key_and_ttl(monkeypatch):
    redis = DayRedis(window={"leafTemperature": [ParcelReading(DEVICE, NOW - 60, 38.0, "CEL")]})
    _wire(monkeypatch, NOW)
    await _run(MetricType.LEAF_TEMPERATURE, redis)
    key = "cwsi_day:tenant-a:p-1:parcel:2026-07-15"
    assert key in redis.json
    assert len(redis.json[key]["results"]) == 1
    assert 24 * 3600 < redis.ttl[key] <= 48 * 3600


@pytest.mark.asyncio
async def test_solar_day_uses_parcel_longitude(monkeypatch):
    # 23:30 UTC at 15 E is 00:30 solar time of the next day.
    late = datetime(2026, 7, 15, 23, 30, tzinfo=timezone.utc)

    async def _coords(*a, **k):
        return (40.0, 15.0)

    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_coords", _coords, raising=False)
    assert await pipeline._local_solar_day("t", "p", late) == date(2026, 7, 16)

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_coords", _none, raising=False)
    assert await pipeline._local_solar_day("t", "p", late) == date(2026, 7, 15)


def _r(v, vpd=3.0):
    return CWSIResult(cwsi=v, vpd_kpa=vpd, temp_canopy=30.0, temp_air=28.0, d1=-1.0, d2=1.0,
                      data_fidelity="onsite_calibrated", temp_source="leaf_temperature", baseline_id="b")


@pytest.mark.asyncio
async def test_day_value_is_the_median_of_stored_results(monkeypatch):
    async def _coords(*a, **k):
        return (40.0, 0.0)

    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_coords", _coords, raising=False)
    store = DayRedis()
    now = datetime.fromtimestamp(NOW, tz=timezone.utc)
    for v in (0.1, 0.7, 0.5):
        out = await pipeline._day_cwsi(store, "t", "p", None, now, _r(v))
    assert out.cwsi == 0.5
    # A call without a CWSI of its own reads the same median.
    assert (await pipeline._day_cwsi(store, "t", "p", None, now, None)).cwsi == 0.5
    # Zones keep their own day.
    assert await pipeline._day_cwsi(store, "t", "p", "z1", now, None) is None
    await pipeline._day_cwsi(store, "t", "p", "z1", now, _r(0.9))
    assert (await pipeline._day_cwsi(store, "t", "p", "z1", now, None)).cwsi == 0.9
    assert (await pipeline._day_cwsi(store, "t", "p", None, now, None)).cwsi == 0.5


@pytest.mark.asyncio
async def test_day_store_failures_degrade_to_the_current_result(monkeypatch):
    async def _coords(*a, **k):
        return (40.0, 0.0)

    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_coords", _coords, raising=False)

    class Down(DayRedis):
        async def get_json(self, key):
            raise StoreError("down")

    now = datetime.fromtimestamp(NOW, tz=timezone.utc)
    cur = _r(0.8)
    assert (await pipeline._day_cwsi(Down(), "t", "p", None, now, cur)) is cur
    assert (await pipeline._day_cwsi(Down(), "t", "p", None, now, None)) is None
    assert (await pipeline._day_cwsi(None, "t", "p", None, now, cur)) is cur
    # A malformed stored entry is skipped, the rest still count.
    store = DayRedis()
    key = pipeline._cwsi_day_key("t", "p", None, now.date())
    store.json[key] = {"results": [{"ts": 1, "result": {"cwsi": "x"}}, {"ts": 2, "result": _r(0.6).model_dump()}]}
    assert (await pipeline._day_cwsi(store, "t", "p", None, now, None)).cwsi == 0.6


@pytest.mark.asyncio
async def test_scheduled_zone_reads_the_day_cwsi(monkeypatch):
    """compute_assessment's zones (no metric) read the zone's stored day CWSI."""
    async def _coords(*a, **k):
        return (40.0, 0.0)

    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_coords", _coords, raising=False)
    now = datetime.fromtimestamp(NOW, tz=timezone.utc)
    store = DayRedis()
    await pipeline._day_cwsi(store, "acme", "p-1", "z1", now, _r(0.7))
    a = CropHealthAssessment(parcel_id="p-1", assessed_at=now, zone_id="z1")
    from app.schemas import PhenologyParams, SoilProperties
    await pipeline._run_engines(
        a, metric_type="", weather=None, phenology=PhenologyParams(),
        redis_state=None, entity_id="p-1", effective_parcel="p-1", tenant_id="acme",
        species="generic", crop_context=None, variety_name=None, gdd=None,
        soil=SoilProperties(), root_depth_mm=600.0, now=now, publish=False, day_store=store,
    )
    assert a.cwsi is not None and a.cwsi.cwsi == 0.7
    assert a.water_stress_indicator.method == "cwsi_sensor"
    assert a.water_stress_indicator.level == "high"


def test_cwsi_attrs_are_stale_cleared():
    for attr in ("cwsiValue", "vpdKpa", "cwsiDataFidelity", "cwsiTempSource"):
        assert attr in pipeline._WATER_STRESS_OPTIONAL_ATTRS
