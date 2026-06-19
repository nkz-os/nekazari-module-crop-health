"""Fix-wave regression tests — unify the keel-contract fields across the two
CropHealthAssessment WRITE paths (sensor webhook `trigger` and scheduled
`compute_assessment`).

Covers:
- F-I2: both paths derive `phenology_stage` from GDD via the shared full table.
- F-I3: live phenology-progress wiring → `phenologyDeviation` / `stageProgressPct`.
- F-I1: persisted `meteoFidelity` (iot_sensor vs parcel_weather).
- F-M4: persisted `seasonStart`.
- F-M5: non-numeric cursor never 500s.
"""
import pytest

from app.services import pipeline
from app.services.meteo_context import MeteoContext


_STAGE_TABLE = {
    "emergence": (0.0, 90.0),
    "vegetative": (90.0, 520.0),
    "flowering": (520.0, 1100.0),
    "maturity": (1100.0, 1600.0),
}


def _patch_common(monkeypatch, *, gdd=300.0, meteo=None):
    """Patch the scheduled-path seams so compute_assessment runs offline."""
    async def _read_crop(parcel_id, tenant_id):
        return {"species": "Zea mays", "plantingDate": "2026-04-15", "variety": "MAS 26 T"}

    async def _stages(species):
        return dict(_STAGE_TABLE)

    async def _gdd(tenant, season_start, base):
        return {"gdd": gdd, "mean_daily_gdd": 10.0}

    captured = {}

    async def _write(entity, tenant_id):
        captured["entity"] = entity
        return True

    async def _meteo(*args, **kwargs):
        return meteo if meteo is not None else MeteoContext(dominant_fidelity="unavailable")

    monkeypatch.setattr(pipeline, "_read_assigned_crop", _read_crop, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_phenology_stages", _stages)
    monkeypatch.setattr(pipeline, "_fetch_gdd", _gdd, raising=False)
    monkeypatch.setattr(pipeline, "_publish_assessment", _write, raising=False)
    monkeypatch.setattr(pipeline, "resolve_meteo_context", _meteo, raising=False)
    return captured


# ── F-I2: unified GDD-derived stage across both paths ──────────────────────


@pytest.mark.asyncio
async def test_both_paths_derive_same_stage_from_gdd(monkeypatch):
    """A scheduled run and a sensor-path run with the same gdd+species set the
    SAME GDD-derived phenology_stage."""
    gdd = 700.0  # lands in 'flowering' (520-1100), NOT the declared/default stage

    # Scheduled path
    _patch_common(monkeypatch, gdd=gdd)
    scheduled = await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t")
    assert scheduled is not None
    assert scheduled.phenology_stage == "flowering"

    # Sensor path: drive _run_engines directly with the same gdd + full table.
    from app.schemas import CropHealthAssessment
    from datetime import datetime, timezone

    phenology = await pipeline.get_phenology_params(species="Zea mays", gdd=gdd)
    sensor_assessment = CropHealthAssessment(
        parcel_id="p1",
        assessed_at=datetime.now(timezone.utc),
        phenology_stage=phenology.stage if phenology else None,  # declared
    )
    await pipeline._run_engines(
        sensor_assessment,
        metric_type="",
        weather=None,
        phenology=phenology,
        redis_state=None,
        entity_id="p1",
        effective_parcel="p1",
        tenant_id="t",
        species="Zea mays",
        crop_context=None,
        variety_name=None,
        gdd=gdd,
        soil=None,
        root_depth_mm=300.0,
        sw_yesterday=None,
        irrigation_mm=0.0,
        now=datetime.now(timezone.utc),
        stage_table=dict(_STAGE_TABLE),
        publish=False,
    )
    assert sensor_assessment.phenology_stage == scheduled.phenology_stage == "flowering"


# ── F-I3: live phenology-progress deviation + stageProgressPct ─────────────


@pytest.mark.asyncio
async def test_phenology_progress_deviation_and_progress_pct_persisted(monkeypatch):
    """GDD beyond the declared stage → deviation != on_track + stageProgressPct,
    both serialised into the NGSI-LD entity."""
    # Declared stage = 'vegetative' (90-520); gdd=700 → ahead into 'flowering'.
    captured = _patch_common(monkeypatch, gdd=700.0)

    async def _params(species="generic", stage="vegetative", **kwargs):
        from app.services.context_client import _DEFAULT_PARAMS
        p = _DEFAULT_PARAMS.model_copy()
        p.stage = "vegetative"  # declared stage trails the GDD
        return p

    monkeypatch.setattr(pipeline, "get_phenology_params", _params, raising=False)

    out = await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t")
    assert out is not None
    assert out.phenology_progress is not None
    assert out.phenology_progress.deviation == "ahead"

    entity = captured["entity"]
    assert entity["phenologyDeviation"]["value"] != "on_track"
    assert entity["phenologyDeviation"]["value"] == "ahead"
    assert "stageProgressPct" in entity
    assert isinstance(entity["stageProgressPct"]["value"], (int, float))


# ── F-I1: persisted meteoFidelity (separate from data_fidelity) ────────────


@pytest.mark.asyncio
async def test_meteo_fidelity_parcel_weather_baseline(monkeypatch):
    """Sensorless run on a weather-map baseline persists meteoFidelity=parcel_weather."""
    meteo = MeteoContext(air_temp_c=22.0, rh_pct=55.0, et0_mm=4.0, dominant_fidelity="parcel_weather")
    captured = _patch_common(monkeypatch, gdd=300.0, meteo=meteo)

    out = await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t")
    assert out is not None
    assert out.meteo_fidelity == "parcel_weather"
    assert captured["entity"]["meteoFidelity"]["value"] == "parcel_weather"
    # data_fidelity (engine vocab) is left untouched / distinct.
    assert out.data_fidelity != "parcel_weather"


@pytest.mark.asyncio
async def test_meteo_fidelity_iot_sensor(monkeypatch):
    """A sensor value in sensor_ctx → meteoFidelity=iot_sensor."""
    meteo = MeteoContext(air_temp_c=24.0, rh_pct=50.0, et0_mm=5.0, dominant_fidelity="iot_sensor")
    captured = _patch_common(monkeypatch, gdd=300.0, meteo=meteo)

    out = await pipeline.compute_assessment(
        "urn:ngsi-ld:AgriParcel:t:p1", "t", sensor_ctx={"air_temp_c": 24.0}
    )
    assert out is not None
    assert out.meteo_fidelity == "iot_sensor"
    assert captured["entity"]["meteoFidelity"]["value"] == "iot_sensor"


# ── F-M4: seasonStart persisted ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_season_start_persisted(monkeypatch):
    captured = _patch_common(monkeypatch, gdd=300.0)
    out = await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t")
    assert out is not None
    assert out.season_start == "2026-04-15"
    assert captured["entity"]["seasonStart"]["value"] == "2026-04-15"


# ── F-M5: non-numeric cursor must not 500 ──────────────────────────────────


def test_non_numeric_cursor_does_not_500(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import setup as setup_mod

    setup_mod.INTERNAL_SECRET = "s"

    seen = {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def query_entities(self, *a, **k):
            seen["offset"] = k.get("offset")
            seen["limit"] = k.get("limit")
            return []

        async def close(self):
            pass

    monkeypatch.setattr("nkz_platform_sdk.orion.OrionClient", _Client)

    client = TestClient(app)
    r = client.post(
        "/api/crop-health/internal/run-scheduled-assessments",
        headers={"X-Internal-Service-Secret": "s"},
        json={"tenant_id": "t", "cursor": "not-a-number", "batch_size": 9999},
    )
    assert r.status_code == 200
    assert seen["offset"] == 0          # bad cursor coerced to 0
    assert seen["limit"] == 500         # batch_size clamped to max
