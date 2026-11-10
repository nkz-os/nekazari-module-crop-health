"""Stage table: cereal answer fields, request params, cache key, zero-width final stage."""
import pytest

from app.engines.phenology_progress import (
    derive_stage_from_gdd, evaluate_phenology_progress, project_stage_timeline,
)
from app.schemas import StageTable
from app.services import context_client

CEREAL = {
    "species": "wheat",
    "stages": [
        {"stage": "emergence", "gddMin": 0.0, "gddMax": 150.0, "baseTemp": 0.0, "bbchFrom": 0, "bbchTo": 9},
        {"stage": "vegetative", "gddMin": 150.0, "gddMax": 1450.0, "baseTemp": 0.0, "bbchFrom": 10, "bbchTo": 49},
        {"stage": "flowering", "gddMin": 1450.0, "gddMax": 1686.4, "baseTemp": 0.0, "bbchFrom": 51, "bbchTo": 69},
        {"stage": "grain_filling", "gddMin": 1686.4, "gddMax": 2809.1, "baseTemp": 0.0, "bbchFrom": 71, "bbchTo": 87},
        {"stage": "maturity", "gddMin": 2809.1, "gddMax": 2809.1, "baseTemp": 0.0, "bbchFrom": 89, "bbchTo": 89},
    ],
    "gddMethod": "aquacrop_m3", "upperCutoff": 26.0, "origin": "sowing",
    "model": {"id": "aquacrop_calendar", "cultivar": "WheatGDD", "version": "3.1.0"},
    "calibration": {"status": "calibrated", "scheme": "es_province", "version": "2026-10-13"},
    "validation": {"status": "measured", "version": "2026-11-10"},
    "sources": [{"short": "s", "detail": "d"}],
}


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def _client(calls, payload):
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, **k):
            calls.append(params)
            return _Resp(payload)

    return _C


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    context_client._stages_cache.clear()
    monkeypatch.setattr(context_client.get_settings(), "bioorchestrator_url", "http://bio", raising=False)
    yield
    context_client._stages_cache.clear()


@pytest.mark.asyncio
async def test_cereal_answer_fields_and_params(monkeypatch):
    calls = []
    monkeypatch.setattr(context_client.httpx, "AsyncClient", _client(calls, CEREAL))
    t = await context_client.get_phenology_stages("wheat", lat=42.8123, lon=-1.6456, irrigation="rainfed")
    assert calls == [{"species": "wheat", "lat": "42.81", "lon": "-1.65", "irrigation": "rainfed"}]
    assert t.gdd_method == "aquacrop_m3" and t.upper_cutoff == 26.0 and t.base_temp == 0.0
    assert t.model["id"] == "aquacrop_calendar" and t.calibration["version"] == "2026-10-13"
    assert t.validation["version"] == "2026-11-10" and t.sources[0]["short"] == "s"
    assert t.origin == "sowing"
    assert t.stage_bbch["emergence"] == (0, 9) and t.stage_bbch["maturity"] == (89, 89)
    assert t.stages["maturity"] == (2809.1, 2809.1)


@pytest.mark.asyncio
async def test_cache_key_has_species_point_and_regime(monkeypatch):
    calls = []
    monkeypatch.setattr(context_client.httpx, "AsyncClient", _client(calls, CEREAL))
    await context_client.get_phenology_stages("wheat", lat=42.81, lon=-1.65, irrigation="rainfed")
    await context_client.get_phenology_stages("wheat", lat=42.811, lon=-1.649, irrigation="rainfed")
    assert len(calls) == 1
    await context_client.get_phenology_stages("wheat", lat=42.81, lon=-1.65, irrigation="irrigated")
    await context_client.get_phenology_stages("wheat", lat=40.0, lon=-1.65, irrigation="rainfed")
    await context_client.get_phenology_stages("wheat")
    await context_client.get_phenology_stages("wheat")
    assert len(calls) == 4
    assert "wheat" in context_client._stages_cache  # the plain request keeps the species-only key


@pytest.mark.asyncio
async def test_other_species_unchanged_and_no_point_params(monkeypatch):
    calls = []
    old = {"species": "Zea mays", "stages": [
        {"stage": "emergence", "gddMin": 0, "gddMax": 90, "baseTemp": 10.0},
        {"stage": "vegetative", "gddMin": 90, "gddMax": 520, "baseTemp": 10.0}]}
    monkeypatch.setattr(context_client.httpx, "AsyncClient", _client(calls, old))
    t = await context_client.get_phenology_stages("Zea mays")
    assert calls == [{"species": "Zea mays"}]
    assert t.gdd_method == "simple_avg_capped" and t.upper_cutoff == 30.0 and t.base_temp == 10.0
    assert t.model is None and t.calibration is None and t.validation is None
    assert t.sources is None and t.stage_bbch == {}


def _table():
    return StageTable(stages={k: (v[0], v[1]) for k, v in {
        "emergence": (0.0, 150.0), "vegetative": (150.0, 1450.0), "flowering": (1450.0, 1686.4),
        "grain_filling": (1686.4, 2809.1), "maturity": (2809.1, 2809.1)}.items()})


@pytest.mark.parametrize("gdd,stage", [(0, "emergence"), (1500, "flowering"), (2809.0, "grain_filling"),
                                       (2809.1, "maturity"), (4000, "maturity")])
def test_derive_with_zero_width_final_stage(gdd, stage):
    assert derive_stage_from_gdd(gdd, _table()) == stage


def test_progress_and_timeline_with_zero_width_final_stage():
    r = evaluate_phenology_progress(3000.0, "maturity", _table())
    assert r.deviation == "on_track" and r.days_to_next_stage is None and r.progress_pct == 0.0
    out = project_stage_timeline(3000.0, _table(), 8.0, __import__("datetime").date(2027, 6, 1))
    last = out[-1]
    assert last["stage"] == "maturity" and last["current"] and last["reached"]
    assert last["projectedDate"] is None and last["projectedEnd"] is None
    early = project_stage_timeline(100.0, _table(), 8.0, __import__("datetime").date(2027, 1, 1))
    assert early[-1]["projectedDate"] is not None and not early[-1]["current"]
