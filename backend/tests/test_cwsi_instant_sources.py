"""Sensor CWSI takes its instantaneous air, RH and Rs only from qualifying sources (spec §14).

R1: a WeatherObserved qualifies only when it is linked to the parcel; the tenant-wide
fallback of ``_regional_meteo`` stays for its other users but never feeds the CWSI.
R2: the CWSI inputs are chosen per variable (parcel sensor, else linked hourly
observation within 1 h), not from the precedence-resolved snapshot, so weather-map's
daily air no longer masks the hourly observation (other engines keep the snapshot).
R3: under-panel air/RH never feeds an open-field CWSI.
"""
from __future__ import annotations

import logging

import pytest

from app.services import pipeline
from app.services.parcel_link import OPEN_FIELD, UNDER_PANEL
from app.services.redis_state import ParcelReading
from tests.test_cwsi_air_and_sky import _cwsi_run
from tests.test_pipeline_under_panel_stress import NOW
from tests.test_post_maturity import _no_network, _offline_context  # noqa: F401  (autouse: offline)

_LINKED = {"air_temp_c": 35.0, "rh_pct": 20.0, "et0_mm": 5.0, "observed_at_ts": NOW - 600,
           "parcel_linked": True}


# ── R1: _regional_meteo marks the parcel-linked observation ─────────────────

def _fake_orion(linked: list, tenant_wide: list):
    class _Resp:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, params=None, headers=None):
            return _Resp(linked if "q" in (params or {}) else tenant_wide)

    return lambda **kw: _Client()


_WO = {"airTemperature": 30, "relativeHumidity": 25, "solarRadiation": 700,
       "dateObserved": "2026-07-15T11:50:00Z"}


@pytest.mark.asyncio
async def test_regional_meteo_marks_linked_observation(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _fake_orion([dict(_WO)], []))
    out = await pipeline._regional_meteo("p-1", "tenant-a")
    assert out["parcel_linked"] is True
    assert out["air_temp_c"] == 30.0


@pytest.mark.asyncio
async def test_regional_meteo_tenant_fallback_is_not_linked_but_kept(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _fake_orion([], [dict(_WO)]))
    out = await pipeline._regional_meteo("p-1", "tenant-a")
    assert out["parcel_linked"] is False
    # Kept for the other users (e.g. under-panel GHI): values and time still returned.
    assert out["solar_radiation_wm2"] == 700.0
    assert out["observed_at_ts"] is not None


@pytest.mark.asyncio
async def test_unlinked_tenant_observation_never_gives_cwsi(monkeypatch, caplog):
    regional = {**_LINKED, "parcel_linked": False}
    with caplog.at_level(logging.INFO):
        a = await _cwsi_run(monkeypatch, regional=regional)
    assert a.cwsi is None
    assert a.water_stress_indicator.method != "cwsi_sensor"
    # The trigger gate (no instantaneous RH) stops it before the helper logs.


@pytest.mark.asyncio
async def test_unflagged_observation_never_gives_cwsi(monkeypatch):
    regional = {k: v for k, v in _LINKED.items() if k != "parcel_linked"}
    a = await _cwsi_run(monkeypatch, regional=regional)
    assert a.cwsi is None


@pytest.mark.asyncio
async def test_unlinked_rs_never_decides_the_sky(monkeypatch):
    # Air/RH from the parcel's sensors; Rs only from an unlinked station -> sky unknown.
    from tests.test_cwsi_air_and_sky import _ref
    by_context = {
        (OPEN_FIELD, "airTemperature"): [ParcelReading("air", NOW - 120, 35.0, "CEL")],
        (OPEN_FIELD, "relativeHumidity"): [ParcelReading("air", NOW - 120, 20.0, "P1")],
    }
    # Overcast Rs from another station must not reject (nor accept) the reading.
    regional = {"solar_radiation_wm2": 1.0, "observed_at_ts": NOW - 600, "parcel_linked": False}
    a = await _cwsi_run(monkeypatch, regional=regional, by_context=by_context,
                        ref=_ref(clear_sky=True), leaf=38.0)
    assert a.cwsi is not None  # high CWSI with unknown sky is kept, not "sky not clear"


# ── R2: per-variable instantaneous choice; weather-map no longer masks it ───

@pytest.mark.asyncio
async def test_linked_hourly_observation_wins_over_weather_map_daily_air(monkeypatch):
    a = await _cwsi_run(monkeypatch, wm={"air_temp_c": 28.0, "et0_mm": 5.0}, regional=dict(_LINKED))
    assert a.cwsi is not None
    assert a.cwsi.temp_air == 35.0


def _capture_meteo(monkeypatch) -> dict:
    """Keep the precedence-resolved MeteoContext the pipeline built (what other engines get)."""
    import tests.test_cwsi_air_and_sky as base
    captured: dict = {}
    real_setup = base._setup

    def _setup(mp, **kw):
        published, seen = real_setup(mp, **kw)
        captured["seen"] = seen
        return published, seen

    monkeypatch.setattr(base, "_setup", _setup)
    return captured


@pytest.mark.asyncio
async def test_other_engines_still_get_weather_map_air(monkeypatch):
    captured = _capture_meteo(monkeypatch)
    a = await _cwsi_run(monkeypatch, wm={"air_temp_c": 28.0, "et0_mm": 5.0}, regional=dict(_LINKED))
    assert a.cwsi is not None
    ctx = captured["seen"]["ctx"]
    assert ctx.air_temp_c == 28.0 and ctx.fidelity["air_temp_c"] == "parcel_weather"


@pytest.mark.asyncio
async def test_sensor_air_and_linked_rh_combine_per_variable(monkeypatch):
    by_context = {(OPEN_FIELD, "airTemperature"): [ParcelReading("air", NOW - 120, 36.0, "CEL")]}
    regional = {"rh_pct": 20.0, "air_temp_c": 30.0, "observed_at_ts": NOW - 600, "parcel_linked": True}
    a = await _cwsi_run(monkeypatch, by_context=by_context, regional=regional)
    assert a.cwsi is not None
    assert a.cwsi.temp_air == 36.0  # the parcel sensor wins over the linked station


@pytest.mark.asyncio
async def test_linked_observation_older_than_one_hour_with_weather_map_no_cwsi(monkeypatch):
    regional = {**_LINKED, "observed_at_ts": NOW - 2 * 3600}
    a = await _cwsi_run(monkeypatch, wm={"air_temp_c": 28.0, "et0_mm": 5.0}, regional=regional)
    assert a.cwsi is None


# ── R3: under-panel air/RH never feeds an open-field CWSI ───────────────────

@pytest.mark.asyncio
async def test_under_panel_air_alone_never_gives_open_field_cwsi(monkeypatch):
    by_context = {
        (UNDER_PANEL, "airTemperature"): [ParcelReading("up", NOW - 120, 35.0, "CEL")],
        (UNDER_PANEL, "relativeHumidity"): [ParcelReading("up", NOW - 120, 20.0, "P1")],
    }
    a = await _cwsi_run(monkeypatch, by_context=by_context)
    assert a.cwsi is None
    assert a.water_stress_indicator.level != "none"


@pytest.mark.asyncio
async def test_open_field_cwsi_ignores_under_panel_air(monkeypatch):
    by_context = {
        (UNDER_PANEL, "airTemperature"): [ParcelReading("up", NOW - 120, 25.0, "CEL")],
        (UNDER_PANEL, "relativeHumidity"): [ParcelReading("up", NOW - 120, 60.0, "P1")],
        (OPEN_FIELD, "airTemperature"): [ParcelReading("of", NOW - 120, 35.0, "CEL")],
        (OPEN_FIELD, "relativeHumidity"): [ParcelReading("of", NOW - 120, 20.0, "P1")],
    }
    captured = _capture_meteo(monkeypatch)
    a = await _cwsi_run(monkeypatch, by_context=by_context)
    assert a.cwsi is not None
    assert a.cwsi.temp_air == 35.0
    # Other engines keep the pooled sensor air (unchanged by this fix).
    assert captured["seen"]["ctx"].air_temp_c == pytest.approx(30.0)


# ── resolver: candidates per variable, best first ───────────────────────────

@pytest.mark.asyncio
async def test_resolver_instant_candidates_sensor_first_linked_only():
    from app.services.meteo_context import resolve_meteo_context

    async def _wm(*a, **k):
        return {"air_temp_c": 28.0}

    async def _linked(*a, **k):
        return {"air_temp_c": 30.0, "rh_pct": 25.0, "observed_at_ts": 100.0, "parcel_linked": True}

    async def _unlinked(*a, **k):
        return {"air_temp_c": 30.0, "rh_pct": 25.0, "observed_at_ts": 100.0, "parcel_linked": False}

    ctx = await resolve_meteo_context(
        "p", "t", sensor_ctx={"air_temp_c": 33.0}, instant_sensor_ctx={"air_temp_c": 34.0},
        weather_map_fn=_wm, regional_fn=_linked,
    )
    assert [(c.source, c.value) for c in ctx.instantaneous["air_temp_c"]] == [
        ("iot_sensor", 34.0), ("regional_proxy", 30.0)]
    assert [(c.source, c.observed_ts) for c in ctx.instantaneous["rh_pct"]] == [("regional_proxy", 100.0)]
    assert ctx.air_temp_c == 33.0  # precedence-resolved value for other engines unchanged

    ctx = await resolve_meteo_context("p", "t", weather_map_fn=_wm, regional_fn=_unlinked)
    assert ctx.instantaneous == {}
    assert ctx.air_temp_c == 28.0 and ctx.rh_pct == 25.0


# ── trigger gate reads the instantaneous RH, not the snapshot RH ────────────

def _rewrite_snapshot(monkeypatch, **changes):
    real = pipeline._snapshot_from_meteo

    def wrapped(meteo):
        snap = real(meteo)
        if snap is None:
            return snap
        inst = dict(snap.instantaneous)
        if changes.pop("drop_inst_rh", False):
            inst.pop("rh_pct", None)
        return snap.model_copy(update={**changes, "instantaneous": inst})

    monkeypatch.setattr(pipeline, "_snapshot_from_meteo", wrapped)


@pytest.mark.asyncio
async def test_gate_uses_instantaneous_rh_when_snapshot_rh_missing(monkeypatch):
    _rewrite_snapshot(monkeypatch, humidity_pct=None)
    a = await _cwsi_run(monkeypatch, regional=dict(_LINKED))
    assert a.cwsi is not None


@pytest.mark.asyncio
async def test_gate_blocks_when_only_snapshot_rh_exists(monkeypatch):
    calls = []
    real = pipeline._ir_cwsi_from_baseline

    async def spy(*a, **k):
        calls.append(1)
        return await real(*a, **k)

    monkeypatch.setattr(pipeline, "_ir_cwsi_from_baseline", spy)
    _rewrite_snapshot(monkeypatch, drop_inst_rh=True)
    a = await _cwsi_run(monkeypatch, regional=dict(_LINKED))
    assert a.cwsi is None
    assert calls == []
