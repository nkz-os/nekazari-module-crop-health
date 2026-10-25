"""Task 4 -- shade-aware water stress wired into the sensor-triggered pipeline.

The real ``_run_engines`` runs; only I/O (context clients, Orion publish,
Redis) is faked.
"""
import types
from datetime import datetime, timezone

import httpx
import pytest

from app.engines.under_panel_stress import ks_from_theta
from app.schemas import MetricType, SoilProperties
from app.services import pipeline
from app.services.redis_state import ParcelReading, StoreError
from app.services.zonation import Zone

NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp()
TODAY = "2026-07-15"
YESTERDAY = "2026-07-14"
PARCEL = "p-1"
_Z0 = {"type": "Polygon", "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]}
_Z1 = {"type": "Polygon", "coordinates": [[[10, 0], [10, 10], [20, 10], [20, 0], [10, 0]]]}


class FakeRedis:
    def __init__(self, readings=None, shade=None, fail=False, shade_ts=None, state=None):
        self.readings = readings or {}
        self.shade = shade or {}
        self.shade_ts = shade_ts or {}
        self.fail = fail
        self.state = state
        self.saved = []

    async def get_balance_state(self, tenant, parcel):
        if self.fail:
            raise StoreError("redis down")
        return self.state

    async def set_balance_state(self, tenant, parcel, day, sw_mm, **extras):
        self.saved.append((parcel, day, sw_mm))
        self.state = {"date": day, "sw_mm": sw_mm, **{k: v for k, v in extras.items() if v is not None}}
        return True

    async def try_lock(self, key, ttl_s):
        return None if self.fail else True

    async def unlock(self, key):
        pass

    async def get_window(self, *a, **k):
        return []

    async def get_latest(self, *a, **k):
        return None

    async def get_parcel_readings(self, tenant, parcel, context, metric, max_age_s, now_ts):
        if self.fail:
            raise RuntimeError("redis down")
        return [r for r in self.readings.get(metric, []) if 0 <= now_ts - r.ts <= max_age_s]

    async def get_daily_shade(self, tenant, parcel, day):
        if self.fail:
            raise RuntimeError("redis down")
        return self.shade.get(day)

    async def get_daily_shade_ts(self, tenant, parcel, day):
        if self.fail:
            raise RuntimeError("redis down")
        return self.shade_ts.get(day)


# A stored daily balance current to yesterday: the sensor path reads it, never steps it.
STATE = {"date": YESTERDAY, "sw_mm": 40.0}


def soil_reading(value, age=60, unit="P1", device="d1"):
    return ParcelReading(device_id=device, ts=NOW - age, value=value, unit_code=unit)


def _setup(monkeypatch, *, wm=None, regional=None, soil=None, zones=None, eppo="OLVEU"):
    wm = {"air_temp_c": 24.0, "rh_pct": 50.0, "et0_mm": 5.0} if wm is None else wm
    regional = {} if regional is None else regional
    soil = soil or SoilProperties(
        has_data=True, hydraulics_from_soil=True, field_capacity=0.27, wilting_point=0.12
    )
    zones = zones or [Zone("parcel", _Z0)]
    crop = types.SimpleNamespace(
        crop=types.SimpleNamespace(eppo=eppo, name="olive"),
        variety=None, management=None, season=None, phenology_source="default",
    )

    async def _none(*a, **k):
        return None

    async def _crop(*a, **k):
        return crop

    async def _stages(species):
        return {}

    async def _params(*a, **k):
        return types.SimpleNamespace(
            stage="vegetative", kc=0.8, mds_ref=100.0, ky=0.45, d1=None, d2=None)

    async def _soil(*a, **k):
        return soil

    async def _geom(*a, **k):
        return _Z0

    async def _zones(*a, **k):
        return zones

    async def _wm(*a, **k):
        return wm

    async def _reg(*a, **k):
        return regional

    monkeypatch.setattr(pipeline, "_now_ts", lambda: NOW)
    monkeypatch.setattr(pipeline.context_client, "get_crop_context", _crop, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_phenology_stages", _stages)
    monkeypatch.setattr(pipeline.context_client, "get_soil_properties", _soil, raising=False)
    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_geometry", _geom, raising=False)
    monkeypatch.setattr(pipeline.context_client, "resolve_season_start", _none, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_soil_susceptibility", _none, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_multiyear_vigor_anomaly", _none, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_penetrometer_data", _none, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_ndvi_climatology", _none, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_lst_climatology", _none, raising=False)
    monkeypatch.setattr(pipeline.context_client, "_resolve_parcel_coords", _none, raising=False)
    monkeypatch.setattr(pipeline, "get_phenology_params", _params, raising=False)
    monkeypatch.setattr(pipeline, "resolve_zones", _zones, raising=False)
    monkeypatch.setattr(pipeline, "_weather_map_meteo", _wm)
    monkeypatch.setattr(pipeline, "_regional_meteo", _reg)
    for name in ("_fetch_parcel_lst_with_date", "_fetch_parcel_lst", "_fetch_parcel_ndvi",
                 "_fetch_parcel_smi", "_fetch_parcel_sar", "_emit_assessment_side_effects"):
        monkeypatch.setattr(pipeline, name, _none, raising=False)

    published = {"assessments": [], "entities": []}

    async def _publish(assessment, tenant_id):
        published["assessments"].append(assessment)
        return True

    async def _publish_entity(entity, tenant_id):
        published["entities"].append(entity)
        return True

    monkeypatch.setattr(pipeline, "publish_assessment", _publish)
    monkeypatch.setattr(pipeline, "_publish_assessment", _publish_entity)

    deletes = []
    delete_behaviour = {"status": None, "error": None}

    class FakeOrion:
        def __init__(self, *a, **k):
            pass

        async def delete_entity_attr(self, entity_id, attr):
            deletes.append((entity_id, attr))
            if delete_behaviour["error"]:
                raise delete_behaviour["error"]
            if delete_behaviour["status"]:
                req = httpx.Request("DELETE", "http://orion.invalid/x")
                raise httpx.HTTPStatusError(
                    "err", request=req, response=httpx.Response(delete_behaviour["status"], request=req))

        async def close(self):
            pass

    monkeypatch.setattr("nkz_platform_sdk.orion.OrionClient", FakeOrion)
    published["deletes"] = deletes
    published["delete_behaviour"] = delete_behaviour

    seen = {}
    real = pipeline.resolve_meteo_context

    async def _spy(*a, **k):
        ctx = await real(*a, **k)
        seen["ctx"] = ctx
        seen["sensor_ctx"] = k.get("sensor_ctx")
        return ctx

    monkeypatch.setattr(pipeline, "resolve_meteo_context", _spy)
    return published, seen


async def _trigger(redis):
    return await pipeline.trigger(
        entity_id="urn:ngsi-ld:DeviceMeasurement:d1",
        metric_type=MetricType.SOIL_MOISTURE.value,
        redis_state=redis,
        parcel_id=PARCEL,
        tenant_id="tenant-a",
    )


def _entity(published):
    return published["assessments"][-1].to_ngsi_ld()


@pytest.mark.asyncio
async def test_trigger_publishes_iot_sensor_index(monkeypatch):
    published, _ = _setup(monkeypatch)
    redis = FakeRedis(readings={"soilMoisture": [soil_reading(15.0)]})
    await _trigger(redis)
    e = _entity(published)
    expected = round(1 - ks_from_theta(0.15, 0.27, 0.12, 0.65), 3)
    assert e["waterStressFidelity"]["value"] == "iot_sensor"
    assert e["waterStressIndex"]["value"] == expected
    assert expected > 0
    obs = e["waterStressObservedAt"]
    assert obs["type"] == "Property"
    assert obs["value"]["@type"] == "DateTime"
    assert obs["value"]["@value"] == datetime.fromtimestamp(NOW - 60, tz=timezone.utc).isoformat()
    assert obs["value"]["@value"].endswith("+00:00")


@pytest.mark.asyncio
async def test_trigger_without_soil_reading_uses_model_fidelity(monkeypatch):
    published, seen = _setup(monkeypatch)
    await _trigger(FakeRedis(state=dict(STATE)))
    e = _entity(published)
    assert seen["ctx"].fidelity["et0_mm"] == "parcel_weather"
    assert e["waterStressFidelity"]["value"] == "parcel_weather"
    assert "waterStressIndex" in e


@pytest.mark.asyncio
async def test_no_index_attribute_when_unavailable(monkeypatch):
    published, _ = _setup(monkeypatch, wm={}, regional={})
    await _trigger(FakeRedis())
    e = _entity(published)
    assert e["waterStressFidelity"]["value"] == "unavailable"
    assert "waterStressIndex" not in e
    assert "waterStressObservedAt" not in e
    assert "shadeFraction" not in e


@pytest.mark.asyncio
async def test_shade_is_published_and_leaves_the_balance_untouched(monkeypatch):
    published, _ = _setup(monkeypatch)
    redis = FakeRedis(shade={TODAY: 0.5}, state=dict(STATE))
    await _trigger(redis)
    a = published["assessments"][-1]
    # The sensor path reads the stored state: no stepping, shade not in the balance, and
    # without stored day flows no back-compat water balance (never a 0 mm read as real).
    assert a.water_balance is None
    assert a.soil_water_balance.sw_mm == STATE["sw_mm"]
    assert redis.saved == []
    assert a.to_ngsi_ld()["shadeFraction"]["value"] == 0.5


@pytest.mark.asyncio
async def test_shade_falls_back_to_yesterday(monkeypatch):
    published, _ = _setup(monkeypatch)
    await _trigger(FakeRedis(shade={YESTERDAY: 0.4}))
    assert published["assessments"][-1].to_ngsi_ld()["shadeFraction"]["value"] == 0.4


@pytest.mark.asyncio
async def test_no_shade_publishes_no_shade_fraction(monkeypatch):
    published, _ = _setup(monkeypatch)
    await _trigger(FakeRedis(state=dict(STATE)))
    a = published["assessments"][-1]
    assert a.soil_water_balance.sw_mm == STATE["sw_mm"]
    assert "shadeFraction" not in a.to_ngsi_ld()


@pytest.mark.asyncio
async def test_air_sensor_overrides_weather_rh(monkeypatch):
    published, seen = _setup(monkeypatch)
    redis = FakeRedis(readings={
        "airTemperature": [soil_reading(30.0, unit="CEL"), soil_reading(32.0, unit="CEL", device="d2")],
        "relativeHumidity": [soil_reading(40.0, unit="P1")],
    })
    await _trigger(redis)
    assert seen["ctx"].fidelity["rh_pct"] == "iot_sensor"
    assert seen["ctx"].rh_pct == 40.0
    assert seen["ctx"].air_temp_c == 31.0


@pytest.mark.asyncio
async def test_out_of_range_air_readings_ignored(monkeypatch):
    published, seen = _setup(monkeypatch)
    redis = FakeRedis(readings={
        "airTemperature": [soil_reading(85.0, unit="CEL")],
        "relativeHumidity": [soil_reading(140.0, unit="P1")],
    })
    await _trigger(redis)
    assert seen["ctx"].fidelity["rh_pct"] == "parcel_weather"
    assert seen["ctx"].fidelity["air_temp_c"] == "parcel_weather"


@pytest.mark.asyncio
async def test_sensor_path_never_writes_the_balance(monkeypatch):
    published, _ = _setup(monkeypatch)
    redis = FakeRedis(readings={"soilMoisture": [soil_reading(20.0)]}, state=dict(STATE))
    await _trigger(redis)
    swb = published["assessments"][-1].soil_water_balance
    # Probes correct the balance only in the scheduled run; the trigger only reads it.
    assert redis.saved == []
    assert redis.state == STATE
    assert swb.sw_mm == STATE["sw_mm"]


@pytest.mark.asyncio
async def test_model_path_persists_model_soil_water(monkeypatch):
    published, _ = _setup(monkeypatch)
    redis = FakeRedis(state=dict(STATE))
    await _trigger(redis)
    swb = published["assessments"][-1].soil_water_balance
    # Without probes the trigger writes nothing: the balance is the stored one.
    assert redis.saved == []
    assert redis.state == STATE
    assert swb.sw_mm == STATE["sw_mm"]


@pytest.mark.asyncio
async def test_trigger_without_state_has_no_balance(monkeypatch):
    published, _ = _setup(monkeypatch)
    redis = FakeRedis(readings={"soilMoisture": [soil_reading(20.0)]})
    await _trigger(redis)
    a = published["assessments"][-1]
    assert a.soil_water_balance is None
    assert redis.saved == []


@pytest.mark.asyncio
async def test_redis_failure_still_publishes_assessment(monkeypatch):
    published, _ = _setup(monkeypatch)
    out = await _trigger(FakeRedis(fail=True))
    assert out is not None
    e = _entity(published)
    # No readable state, no balance: no model index rather than a cold-started one.
    assert out.soil_water_balance is None
    assert e["waterStressFidelity"]["value"] == "unavailable"
    assert "shadeFraction" not in e


@pytest.mark.asyncio
async def test_soil_without_data_gives_regional_proxy(monkeypatch):
    published, _ = _setup(monkeypatch, soil=SoilProperties(has_data=False))
    redis = FakeRedis(readings={"soilMoisture": [soil_reading(15.0)]})
    await _trigger(redis)
    assert _entity(published)["waterStressFidelity"]["value"] == "regional_proxy"


@pytest.mark.asyncio
async def test_zonal_rollup_carries_stress_zones_do_not(monkeypatch):
    published, _ = _setup(
        monkeypatch, zones=[Zone("z0", _Z0), Zone("z1", _Z1)])

    async def _nocoords(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "_resolve_device_coords", _nocoords, raising=False)
    redis = FakeRedis(
        readings={"soilMoisture": [soil_reading(15.0)]}, shade={TODAY: 0.5}, state=dict(STATE))
    await _trigger(redis)
    zone_ents = [e for e in published["entities"] if e["type"] == "CropHealthZoneAssessment"]
    parcel_ents = [e for e in published["entities"] if e["type"] == "CropHealthAssessment"]
    assert len(zone_ents) == 2 and len(parcel_ents) == 1
    for z in zone_ents:
        for k in ("waterStressIndex", "waterStressFidelity", "waterStressObservedAt", "shadeFraction", "shadeObservedAt"):
            assert k not in z
    p = parcel_ents[0]
    assert p["waterStressFidelity"]["value"] == "iot_sensor"
    assert p["waterStressIndex"]["value"] > 0
    assert p["shadeFraction"]["value"] == 0.5
    # The trigger never writes the balance; every zone carries the parcel balance.
    assert redis.saved == []
    sw = [e["soilWaterMm"]["value"] for e in published["entities"] if "soilWaterMm" in e]
    assert sw and all(v == pytest.approx(redis.state["sw_mm"], abs=0.01) for v in sw)


def test_olive_eppo_depletion_fraction():
    assert pipeline._DEPLETION_FRACTION_P["OLVEU"] == 0.65


ENTITY_ID = "urn:ngsi-ld:CropHealthAssessment:p-1-20260715"


@pytest.mark.asyncio
async def test_unavailable_after_iot_clears_stale_attributes(monkeypatch):
    published, _ = _setup(monkeypatch)
    await _trigger(FakeRedis(
        readings={"soilMoisture": [soil_reading(15.0)]}, shade={TODAY: 0.5}, shade_ts={TODAY: NOW - 60}))
    assert published["deletes"] == []  # everything present, nothing stale
    # later same-day trigger: nothing computable
    published2, _ = _setup(monkeypatch, wm={}, regional={})
    await _trigger(FakeRedis())
    ids = {d[0] for d in published2["deletes"]}
    attrs = {d[1] for d in published2["deletes"]}
    assert ids == {published2["assessments"][-1].to_ngsi_ld()["id"]}
    assert attrs == {
        "waterStressIndex", "waterStressObservedAt", "shadeFraction", "shadeObservedAt",
        "underPanelWaterStressIndex", "underPanelWaterStressFidelity",
        "underPanelWaterStressObservedAt",
    }


@pytest.mark.asyncio
async def test_only_omitted_attrs_are_deleted(monkeypatch):
    published, _ = _setup(monkeypatch)
    await _trigger(FakeRedis(state=dict(STATE)))  # model path: index+observedAt present, shade None
    assert [d[1] for d in published["deletes"]] == [
        "shadeFraction", "shadeObservedAt",
        "underPanelWaterStressIndex", "underPanelWaterStressFidelity",
        "underPanelWaterStressObservedAt",
    ]


@pytest.mark.asyncio
async def test_delete_404_is_success(monkeypatch):
    published, _ = _setup(monkeypatch, wm={}, regional={})
    published["delete_behaviour"]["status"] = 404
    out = await _trigger(FakeRedis())
    assert out is not None
    assert len(published["deletes"]) == 7  # does not stop after the first 404


@pytest.mark.asyncio
async def test_delete_error_does_not_fail_trigger(monkeypatch):
    published, _ = _setup(monkeypatch, wm={}, regional={})
    published["delete_behaviour"]["error"] = RuntimeError("boom")
    out = await _trigger(FakeRedis())
    assert out is not None
    assert len(published["assessments"]) == 1


@pytest.mark.asyncio
async def test_zonal_rollup_clears_stale_attributes(monkeypatch):
    published, _ = _setup(monkeypatch, zones=[Zone("z0", _Z0), Zone("z1", _Z1)], wm={}, regional={})

    async def _nocoords(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "_resolve_device_coords", _nocoords, raising=False)
    await _trigger(FakeRedis())
    parcel = [e for e in published["entities"] if e["type"] == "CropHealthAssessment"][0]
    assert {d[0] for d in published["deletes"]} == {parcel["id"]}
    assert len(published["deletes"]) == 7


@pytest.mark.asyncio
async def test_defaulted_hydraulics_with_has_data_is_regional_proxy(monkeypatch):
    soil = SoilProperties(has_data=True, hydraulics_from_soil=False)
    published, _ = _setup(monkeypatch, soil=soil)
    await _trigger(FakeRedis(readings={"soilMoisture": [soil_reading(15.0)]}))
    assert _entity(published)["waterStressFidelity"]["value"] == "regional_proxy"


@pytest.mark.asyncio
async def test_dead_probe_reading_is_not_iot_sensor(monkeypatch):
    published, _ = _setup(monkeypatch)
    await _trigger(FakeRedis(readings={"soilMoisture": [soil_reading(0.0)]}, state=dict(STATE)))
    assert _entity(published)["waterStressFidelity"]["value"] == "parcel_weather"


@pytest.mark.asyncio
async def test_sensor_air_temp_without_et0_gives_no_index(monkeypatch):
    published, _ = _setup(monkeypatch, wm={}, regional={})
    air = ParcelReading("d2", NOW - 60, 24.0, "CEL")
    await _trigger(FakeRedis(readings={MetricType.AIR_TEMPERATURE.value: [air]}))
    e = _entity(published)
    assert e["waterStressFidelity"]["value"] == "unavailable"
    assert "waterStressIndex" not in e


@pytest.mark.asyncio
async def test_no_soil_water_balance_without_et0(monkeypatch):
    published, _ = _setup(monkeypatch, wm={}, regional={})
    air = ParcelReading("d2", NOW - 60, 24.0, "CEL")
    redis = FakeRedis(readings={MetricType.AIR_TEMPERATURE.value: [air]})
    await _trigger(redis)
    a = published["assessments"][-1]
    # Without stored state the trigger never computes a balance of its own.
    assert a.soil_water_balance is None
    assert a.water_balance is None
    assert redis.saved == []


@pytest.mark.asyncio
async def test_stored_balance_without_live_et0_gives_index(monkeypatch):
    published, _ = _setup(monkeypatch, wm={}, regional={})
    redis = FakeRedis(state=dict(STATE))
    await _trigger(redis)
    a = published["assessments"][-1]
    # The model index comes from the stored daily balance, not from the live ET0.
    assert a.soil_water_balance.sw_mm == STATE["sw_mm"]
    assert redis.saved == []
    e = _entity(published)
    assert e["waterStressFidelity"]["value"] == "parcel_weather"
    assert "waterStressIndex" in e


DAY_FLOWS = {"precip_mm": 3.0, "etc_mm": 2.4, "actual_et_mm": 2.0, "deep_percolation_mm": 0.0}


@pytest.mark.asyncio
async def test_read_only_balance_uses_the_stored_day_flows(monkeypatch):
    published, _ = _setup(monkeypatch)
    await _trigger(FakeRedis(state=dict(STATE, **DAY_FLOWS)))
    a = published["assessments"][-1]
    assert (a.water_balance.precip_mm, a.water_balance.etc_mm) == (3.0, 2.4)
    e = a.to_ngsi_ld()
    assert e["actualETmm"]["value"] == 2.0
    assert e["deepPercolationMm"]["value"] == 0.0


@pytest.mark.asyncio
async def test_read_only_balance_without_flows_omits_them(monkeypatch):
    published, _ = _setup(monkeypatch)
    await _trigger(FakeRedis(state=dict(STATE)))
    a = published["assessments"][-1]
    e = a.to_ngsi_ld()
    assert a.water_balance is None
    assert "actualETmm" not in e and "deepPercolationMm" not in e
    assert e["soilWaterMm"]["value"] == STATE["sw_mm"]


@pytest.mark.asyncio
async def test_trigger_reads_the_saved_root_depth(monkeypatch):
    # Generic crop without GDD: the trigger resolves 300 mm; the state was saved at 800 mm.
    published, _ = _setup(monkeypatch, eppo="ZZZZZ")
    await _trigger(FakeRedis(state=dict(STATE, sw_mm=100.0, root_depth_mm=800.0)))
    swb = published["assessments"][-1].soil_water_balance
    assert swb.awc_mm == pytest.approx((0.27 - 0.12) * 800.0)
    assert swb.excess_mm == 0.0
    assert swb.sw_mm == 100.0


@pytest.mark.asyncio
async def test_shade_observed_at_published_with_shade(monkeypatch):
    published, _ = _setup(monkeypatch)
    ts = NOW - 120
    await _trigger(FakeRedis(shade={TODAY: 0.5}, shade_ts={TODAY: ts}))
    e = _entity(published)
    v = e["shadeObservedAt"]["value"]
    assert v["@type"] == "DateTime"
    assert v["@value"] == datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


@pytest.mark.asyncio
async def test_shade_observed_at_omitted_and_cleared_without_shade(monkeypatch):
    published, _ = _setup(monkeypatch)
    await _trigger(FakeRedis())
    assert "shadeObservedAt" not in _entity(published)
    assert "shadeObservedAt" in [d[1] for d in published["deletes"]]


@pytest.mark.asyncio
async def test_missing_susceptibility_score_skips_compaction(monkeypatch, caplog):
    published, _ = _setup(monkeypatch)

    async def _susc(*a, **k):
        return {"overall_score": None, "overall_class": None}

    monkeypatch.setattr(pipeline.context_client, "get_soil_susceptibility", _susc, raising=False)
    await _trigger(FakeRedis(readings={"soilMoisture": [soil_reading(15.0)]}))
    assert published["assessments"][-1].compaction_risk is None
    assert "compaction risk evaluation failed" not in caplog.text
