"""Post-maturity: GDD gate plus NDVI confirmation, phase basis, baseline id, history level."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.schemas import (
    CropHealthAssessment, CWSIResult, PhenologyParams, SoilProperties, StageTable,
    WaterStressReference,
)
from app.services import pipeline
from tests.test_pipeline_zone_products import FakeOrion, PARCEL, PARCEL_URN, ZONE_URN

_REAL_SERIES = pipeline._fetch_ndvi_series  # the autouse fixture stubs the module attribute

@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail the test if anything tries a real connection (code under test swallows errors)."""
    import socket
    import traceback

    attempts: list[str] = []

    def _record(*args, **kwargs):
        frames = [f for f in traceback.extract_stack() if "/app/" in f.filename]
        attempts.append(f"{args[:1]} from {frames[-1].name if frames else '?'}")
        raise OSError("network disabled in this test module")

    monkeypatch.setattr(socket, "getaddrinfo", _record)
    monkeypatch.setattr(socket.socket, "connect", _record)
    yield
    assert not attempts, f"real network access attempted: {attempts}"


@pytest.fixture(autouse=True)
def _offline_context(monkeypatch):
    """Stub every Orion / soil lookup the engine core makes besides the NDVI series."""
    from app.services import context_client as cc

    def _const(value):
        async def _f(*a, **k):
            return value
        return _f

    for name, value in {
        "_resolve_parcel_coords": None, "_resolve_parcel_geometry": None,
        "get_lst_climatology": cc._climatology_unavailable_lst("stub"),
        "get_ndvi_climatology": cc._climatology_unavailable("stub"),
        "get_soil_susceptibility": None, "get_multiyear_vigor_anomaly": None,
        "get_penetrometer_data": None, "get_agri_crop": None,
        "get_soil_properties": SoilProperties(),
    }.items():
        monkeypatch.setattr(cc, name, _const(value))
    for name, value in {
        "_fetch_parcel_ndvi": (None, "unavailable"), "_fetch_parcel_lst_with_date": None,
        "_fetch_parcel_lst": None, "_fetch_parcel_smi": (None, "unavailable"),
        "_fetch_parcel_sar": (None, "unavailable"), "_fetch_ndvi_series": [],
    }.items():
        monkeypatch.setattr(pipeline, name, _const(value))


NOW = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
START = date(2026, 3, 1)

TABLE = {
    "emergence": (0.0, 100.0), "tillering": (100.0, 500.0), "heading": (500.0, 1100.0),
    "maturity": (1100.0, 1600.0),
}
GREEN_THEN_DROP = [0.20, 0.30, 0.50, 0.70, 0.85, 0.86, 0.85, 0.70, 0.45, 0.25, 0.20]
STILL_GREEN = [0.20, 0.30, 0.50, 0.70, 0.85, 0.86, 0.85, 0.84, 0.82, 0.80]


def _series(values, step=10):
    return [(START + timedelta(days=i * step), v) for i, v in enumerate(values)]


def _ref(post=True, senescence=True, gate="heading"):
    stages = {
        "tillering": {"waterSensitive": True, "sourceIds": ["fao66"]},
        "heading": {"waterSensitive": True, "sourceIds": ["fao66"]},
        "maturity": {"waterSensitive": True, "sourceIds": ["fao66"]},
    }
    if post:
        stages["post_maturity"] = {"waterSensitive": False, "rdiTolerant": False, "sourceIds": ["fao66"]}
    raw = {"baselines": [], "stages": stages}
    if senescence:
        raw["senescence"] = {"method": "timesat_amplitude", "endFraction": 0.2, "gateStage": gate,
                             "sourceId": "timesat", "ref": "Users Guide"}
    return WaterStressReference.model_validate(raw)


async def _engines(ref, gdd, series, *, zone_urn=None, calls=None):
    a = CropHealthAssessment(parcel_id=PARCEL, assessed_at=NOW)

    async def _fake_series(tenant_id, parcel_id, zone, since):
        if calls is not None:
            calls.append((tenant_id, parcel_id, zone, since))
        return series

    with patch.object(pipeline, "_fetch_ndvi_series", _fake_series):
        await pipeline._run_engines(
            a, metric_type="", weather=None,
            phenology=PhenologyParams(stage="flowering", water_stress_reference=ref),
            redis_state=None, entity_id=PARCEL, effective_parcel=PARCEL, tenant_id="acme",
            species="generic", crop_context=None, variety_name=None, gdd=gdd,
            soil=SoilProperties(), root_depth_mm=600.0, now=NOW, publish=False,
            stage_table=StageTable(stages=dict(TABLE)), zone_urn=zone_urn, season_start="2026-03-01",
        )
    return a


# ── reference parsing ────────────────────────────────────────────────────────

def test_malformed_senescence_keeps_reference(caplog):
    raw = {
        "baselines": [],
        "stages": {"heading": {"waterSensitive": True, "sourceIds": ["fao66"]}},
        "sourceIds": ["fao66"],
        "senescence": {"method": "timesat_amplitude", "endFraction": "x"},
        "citations": [{"sourceId": "fao66"}],  # text missing
    }
    with caplog.at_level(logging.WARNING):
        ref = WaterStressReference.model_validate(raw)
    assert ref.senescence is None and ref.citations == []
    assert list(ref.stages) == ["heading"] and ref.source_ids == ["fao66"]
    assert len([r for r in caplog.records if "senescence" in r.getMessage() or "citations" in r.getMessage()]) == 2


def test_valid_senescence_and_citations_parse():
    ref = WaterStressReference.model_validate({
        "senescence": {"method": "timesat_amplitude", "endFraction": 0.2, "gateStage": "silking",
                       "sourceId": "timesat", "ref": "r"},
        "citations": [{"sourceId": "fao66", "text": "FAO-66", "url": "https://example.org/x"}],
    })
    assert ref.senescence.end_fraction == 0.2 and ref.senescence.gate_stage == "silking"
    assert ref.citations[0].source_id == "fao66" and ref.citations[0].url == "https://example.org/x"
    # an unknown method is not a rule crop-health can apply
    other = WaterStressReference.model_validate({"senescence": {
        "method": "other", "endFraction": 0.2, "gateStage": "heading", "sourceId": "s"}})
    assert other.senescence is None


# ── gate + NDVI confirmation ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_maturity_requires_gate_and_ndvi():
    # At the gate (heading) with a confirmed end of season: post-maturity flags apply.
    a = await _engines(_ref(), 700.0, _series(GREEN_THEN_DROP))
    assert a.water_stress_indicator.level == "not_needed"
    assert a.water_stress_phase_basis == "gdd_ndvi"
    assert "fao66" in a.water_stress_indicator.source_ids
    # NDVI confirms but GDD says the crop has not reached the gate: never post-maturity.
    early = await _engines(_ref(), 300.0, _series(GREEN_THEN_DROP))
    assert early.phenology_stage == "tillering"
    assert early.water_stress_indicator.level == "no_data" and early.water_stress_phase_basis == "gdd"
    # Gate reached but the NDVI is still green: normal stage flags.
    green = await _engines(_ref(), 700.0, _series(STILL_GREEN))
    assert green.water_stress_indicator.level == "no_data" and green.water_stress_phase_basis == "gdd"
    # Reference without post_maturity or without senescence: normal stage flags.
    for ref in (_ref(post=False), _ref(senescence=False)):
        b = await _engines(ref, 700.0, _series(GREEN_THEN_DROP))
        assert b.water_stress_phase_basis == "gdd" and b.water_stress_indicator.level == "no_data"
    # A gate stage that is not in the table never opens the gate.
    c = await _engines(_ref(gate="silking"), 700.0, _series(GREEN_THEN_DROP))
    assert c.water_stress_phase_basis == "gdd"


@pytest.mark.asyncio
async def test_no_ndvi_series_keeps_stage_flags():
    for series in ([], _series([0.2, 0.8, 0.3])):
        a = await _engines(_ref(), 1200.0, series)
        assert a.phenology_stage == "maturity"
        assert a.water_stress_indicator.level == "no_data"
        assert a.water_stress_phase_basis == "gdd"


@pytest.mark.asyncio
async def test_no_gdd_never_post_maturity_and_no_basis():
    calls: list = []
    a = await _engines(_ref(), None, _series(GREEN_THEN_DROP), calls=calls)
    assert a.water_stress_phase_basis is None and calls == []  # no series fetched without a gate


@pytest.mark.asyncio
async def test_season_start_missing_falls_back_to_240_days():
    calls: list = []
    a = CropHealthAssessment(parcel_id=PARCEL, assessed_at=NOW)

    async def _fake(tenant_id, parcel_id, zone, since):
        calls.append(since)
        return []

    with patch.object(pipeline, "_fetch_ndvi_series", _fake):
        await pipeline._run_engines(
            a, metric_type="", weather=None,
            phenology=PhenologyParams(stage="flowering", water_stress_reference=_ref()),
            redis_state=None, entity_id=PARCEL, effective_parcel=PARCEL, tenant_id="acme",
            species="generic", crop_context=None, variety_name=None, gdd=700.0,
            soil=SoilProperties(), root_depth_mm=600.0, now=NOW, publish=False,
            stage_table=StageTable(stages=dict(TABLE)),
        )
    assert calls == [NOW.date() - timedelta(days=240)]


# ── NDVI series query ────────────────────────────────────────────────────────

def _eo(owner_attr, owner, day, ndvi):
    d = (START + timedelta(days=day)).isoformat()
    return {"id": f"urn:ngsi-ld:EOProduct:{owner}:{d}", "type": "EOProduct", owner_attr: owner,
            "sensingDate": d, "ndvi": ndvi}


@pytest.mark.asyncio
async def test_series_query_zone_and_parcel():
    fo = FakeOrion([
        _eo("hasAgriParcelZone", ZONE_URN, 20, 0.5), _eo("hasAgriParcelZone", ZONE_URN, 0, 0.2),
        _eo("hasAgriParcelZone", ZONE_URN, 40, None),
        _eo("hasAgriParcel", PARCEL_URN, 10, 0.9), _eo("hasAgriParcel", PARCEL_URN, 30, "bad"),
    ])
    with patch("nkz_platform_sdk.orion.OrionClient", return_value=fo):
        zone = await _REAL_SERIES("acme", PARCEL, ZONE_URN, START)
        parcel = await _REAL_SERIES("acme", PARCEL, None, START)
    assert zone == [(START, 0.2), (START + timedelta(days=20), 0.5)]
    assert parcel == [(START + timedelta(days=10), 0.9)]
    assert f'sensingDate>="{START.isoformat()}"' in fo.queries[0] and "hasAgriParcelZone" in fo.queries[0]
    assert "hasAgriParcelZone" not in fo.queries[1]


@pytest.mark.asyncio
async def test_series_query_failure_is_empty():
    class Boom:
        async def query_entities(self, **kw):
            raise RuntimeError("orion down")

        async def close(self):
            pass

    with patch("nkz_platform_sdk.orion.OrionClient", return_value=Boom()):
        assert await _REAL_SERIES("acme", PARCEL, None, START) == []


# ── Orion attrs, API fields, history ─────────────────────────────────────────

def _cwsi(baseline_id="b1"):
    return CWSIResult(cwsi=0.3, vpd_kpa=3.0, temp_canopy=30.0, temp_air=35.0, d1=-2.0, d2=2.0,
                      baseline_id=baseline_id)


def test_phase_basis_and_baseline_id_attrs_written_and_cleared():
    a = CropHealthAssessment(parcel_id="p", assessed_at=NOW, cwsi=_cwsi(), water_stress_phase_basis="gdd_ndvi")
    e = a.to_ngsi_ld()
    assert e["waterStressPhaseBasis"]["value"] == "gdd_ndvi"
    assert e["cwsiBaselineId"]["value"] == "b1"
    bare = CropHealthAssessment(parcel_id="p", assessed_at=NOW, cwsi=_cwsi(None)).to_ngsi_ld()
    assert "waterStressPhaseBasis" not in bare and "cwsiBaselineId" not in bare
    for attr in ("waterStressPhaseBasis", "cwsiBaselineId"):
        assert attr in pipeline._WATER_STRESS_OPTIONAL_ATTRS
    from app.api.assessment_mapper import map_entity_to_assessment
    m = map_entity_to_assessment(e)
    assert m["waterStressPhaseBasis"] == "gdd_ndvi" and m["cwsiBaselineId"] == "b1"
    m2 = map_entity_to_assessment(bare)
    assert m2["waterStressPhaseBasis"] is None and m2["cwsiBaselineId"] is None


def _zone_result(zone_id, basis, level="not_needed"):
    from app.engines.water_stress_level import WaterStressIndicator
    return CropHealthAssessment(
        parcel_id="p", assessed_at=NOW, zone_id=zone_id, phenology_stage="maturity",
        gdd_accumulated=1200.0, water_stress_phase_basis=basis,
        water_stress_indicator=WaterStressIndicator(level, "none"),
    )


def _rollup_of(zones, parcel_gdd):
    import types
    from app.schemas import WaterStress
    rollup = pipeline._aggregate_rollup("p", zones)
    rollup.water_stress = WaterStress(index=0.9, fidelity="parcel_weather", observed_at=None,
                                      shade_fraction=None)  # Ks 0.1 -> high
    pipeline._refresh_rollup_level(
        rollup, types.SimpleNamespace(water_stress_reference=_ref()), zones,
        parcel_gdd=parcel_gdd, stage_table=StageTable(stages=dict(TABLE)),
    )
    return rollup


def test_one_confirming_zone_does_not_switch_off_the_parcel_alarm():
    for order in (("gdd_ndvi", "gdd"), ("gdd", "gdd_ndvi")):
        zones = [_zone_result("z0", order[0], "not_needed" if order[0] == "gdd_ndvi" else "no_data"),
                 _zone_result("z1", order[1], "not_needed" if order[1] == "gdd_ndvi" else "no_data")]
        r = _rollup_of(zones, 1200.0)
        assert r.water_stress_indicator.level == "high", order
        assert r.water_stress_phase_basis == "gdd"


def test_unanimous_zones_and_parcel_gate_give_not_needed():
    zones = [_zone_result("z0", "gdd_ndvi"), _zone_result("z1", "gdd_ndvi")]
    r = _rollup_of(zones, 1200.0)
    assert r.water_stress_indicator.level == "not_needed" and r.water_stress_phase_basis == "gdd_ndvi"
    # the parcel's own GDD stage must pass the gate too
    low = _rollup_of([_zone_result("z0", "gdd_ndvi"), _zone_result("z1", "gdd_ndvi")], 300.0)
    assert low.water_stress_indicator.level == "high" and low.water_stress_phase_basis == "gdd"


@pytest.mark.asyncio
async def test_zone_path_uses_zone_series_and_gdd():
    """Through _assess_zone: parcel GDD + each zone's own delta decide each zone's gate."""
    from app.services.zonation import Zone
    sq = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    z_hi = Zone("hi", sq, urn="urn:ngsi-ld:AgriParcelZone:acme:p1:hi")
    z_lo = Zone("lo", sq, urn="urn:ngsi-ld:AgriParcelZone:acme:p1:lo")
    seen: list = []

    async def _series_by_zone(tenant_id, parcel_id, zone, since):
        seen.append((zone, since))
        return _series(GREEN_THEN_DROP)

    async def _meteo(*a, **k):
        from app.services.meteo_context import MeteoContext
        return MeteoContext(dominant_fidelity="unavailable")

    crop_ctx = {
        "phenology": PhenologyParams(stage="flowering", water_stress_reference=_ref()),
        "thresholds": StageTable(stages=dict(TABLE)), "gdd": 450.0, "species": "generic",
        "variety_name": None, "now": NOW, "season_start": "2026-03-01",
        "soil": SoilProperties(), "root_depth_mm": 600.0,
    }
    with patch.object(pipeline, "_fetch_ndvi_series", _series_by_zone), \
         patch.object(pipeline, "resolve_meteo_context", _meteo):
        hi = await pipeline._assess_zone(z_hi, "urn:ngsi-ld:AgriParcel:acme:p1", "p1", "acme",
                                         crop_ctx, None, False, gdd_delta=+100.0)
        lo = await pipeline._assess_zone(z_lo, "urn:ngsi-ld:AgriParcel:acme:p1", "p1", "acme",
                                         crop_ctx, None, False, gdd_delta=-50.0)
    assert (hi.phenology_stage, hi.water_stress_phase_basis) == ("heading", "gdd_ndvi")
    assert hi.water_stress_indicator.level == "not_needed"
    assert (lo.phenology_stage, lo.water_stress_phase_basis) == ("tillering", "gdd")
    # only the zone above the gate asked for a series, and it asked for its own zone's
    assert seen == [(z_hi.urn, START)]


def test_history_includes_level():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import assessments

    app = FastAPI()
    app.include_router(assessments.router, prefix="/api/crop-health")
    client = TestClient(app)
    with patch("httpx.AsyncClient") as mock_http:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"data": [
            {"observed_at": "2026-09-02T10:00:00Z", "cwsiValue": 0.2, "waterStressLevel": "mild"},
            {"observed_at": "2026-09-01T10:00:00Z", "cwsiValue": 0.1},
        ]})
        get = AsyncMock(return_value=resp)
        mock_http.return_value.__aenter__.return_value.get = get
        out = client.get("/api/crop-health/assessments/history?parcelId=p1&days=7",
                         headers={"X-Tenant-ID": "acme"})
    assert out.status_code == 200
    assert "waterStressLevel" in get.call_args.kwargs["params"]["attrs"]
    pts = out.json()["points"]
    assert pts[1]["waterStressLevel"] == "mild" and pts[0]["waterStressLevel"] is None


def test_zone_without_phase_basis_blocks_parcel_post_maturity():
    zones = [_zone_result("z0", "gdd_ndvi"), _zone_result("z1", None, "no_data")]
    r = _rollup_of(zones, 1200.0)
    assert r.water_stress_indicator.level == "high" and r.water_stress_phase_basis == "gdd"


def test_published_stage_follows_parcel_gdd_stage_when_flags_are_the_parcels():
    zones = [_zone_result("z0", "gdd_ndvi"), _zone_result("z1", "gdd")]  # zones say "maturity"
    r = _rollup_of(zones, 700.0)  # parcel GDD 700 -> heading
    assert r.phenology_stage == "heading" and r.water_stress_phase_basis == "gdd"
