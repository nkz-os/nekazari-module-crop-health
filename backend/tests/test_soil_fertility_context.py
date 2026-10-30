"""Lab fertility context: stock conversion, None semantics, penetrometer horizons.

Contract: internal-docs-local/specs/2026-10-30-npk-and-penetrometer-contract.md
"""
import pytest
from app.services import context_client
from app.services.context_client import _fertility_from_horizons


# ── _fertility_from_horizons ──────────────────────────────────────────────


def test_no_lab_analysis_returns_empty():
    assert _fertility_from_horizons([{"depthFrom": 0, "depthTo": 30, "sand": 40}]) == {}


def test_subsurface_only_analysis_is_ignored():
    # Contract §4: only the surface horizon may supply fertility.
    out = _fertility_from_horizons([{"depthFrom": 25, "depthTo": 50, "nitrateN": 10.0}])
    assert out == {}


def test_stock_math_with_bulk_density():
    # factor = d_cm x rho x 0.1 = 30 x 1.4 x 0.1 = 4.2
    out = _fertility_from_horizons([{
        "depthFrom": 0, "depthTo": 30, "bulkDensity": 1.4,
        "nitrateN": 10.0, "ammoniumN": 5.0,
        "phosphorusAvailable": 12.0, "phosphorusMethod": "olsen",
        "potassiumExchangeable": 150.0, "potassiumMethod": "ammonium_acetate",
    }])
    assert out["nitrogen_kg_ha"] == pytest.approx(15.0 * 4.2, abs=0.1)
    assert out["phosphorus_kg_ha"] == pytest.approx(12.0 * 4.2, abs=0.1)
    assert out["potassium_kg_ha"] == pytest.approx(150.0 * 4.2, abs=0.1)
    assert out["phosphorus_method"] == "olsen"
    assert out["potassium_method"] == "ammonium_acetate"
    assert out["nitrate_n_mg_kg"] == pytest.approx(10.0)


def test_stock_math_default_bulk_density_and_partial_depth():
    # d = 25 cm (partial horizon), rho fallback 1.35 -> factor 3.375
    out = _fertility_from_horizons([{
        "depthFrom": 0, "depthTo": 25, "phosphorusAvailable": 10.0,
    }])
    assert out["phosphorus_kg_ha"] == pytest.approx(33.8, abs=0.1)


def test_total_nitrogen_mineralizable_path():
    # Only totalNitrogen (%): (0.15 x 10000 x 0.015) x 4.05 = 91.1
    out = _fertility_from_horizons([{
        "depthFrom": 0, "depthTo": 30, "totalNitrogen": 0.15,
    }])
    assert out["nitrogen_kg_ha"] == pytest.approx(91.1, abs=0.2)
    assert out.get("phosphorus_kg_ha") is None


def test_surface_wins_over_subsurface_when_both_present():
    out = _fertility_from_horizons([
        {"depthFrom": 0, "depthTo": 30, "nitrateN": 8.0},
        {"depthFrom": 30, "depthTo": 60, "nitrateN": 40.0},
    ])
    assert out["nitrate_n_mg_kg"] == pytest.approx(8.0)


# ── get_nutrient_recommendation: None params are omitted ──────────────────


@pytest.mark.asyncio
async def test_nutrient_none_params_omitted(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        def json(self):
            return {"recommendations": []}

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None, **k):
            captured["params"] = params
            return _Resp()

    monkeypatch.setattr(context_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(context_client.get_settings(), "bioorchestrator_url", "http://bio", raising=False)
    await context_client.get_nutrient_recommendation("TRZAX", "vegetative")
    assert captured["params"] == {"species": "TRZAX", "stage": "vegetative"}


@pytest.mark.asyncio
async def test_nutrient_real_stocks_forwarded(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        def json(self):
            return {"recommendations": []}

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None, **k):
            captured["params"] = params
            return _Resp()

    monkeypatch.setattr(context_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(context_client.get_settings(), "bioorchestrator_url", "http://bio", raising=False)
    await context_client.get_nutrient_recommendation(
        "TRZAX", "vegetative", soil_n=63.0, soil_p=50.4, soil_k=607.5,
    )
    assert captured["params"]["soil_n"] == 63.0
    assert captured["params"]["soil_p"] == 50.4
    assert captured["params"]["soil_k"] == 607.5


# ── get_penetrometer_data: horizons first, root fallback ──────────────────


@pytest.mark.asyncio
async def _run_penetrometer(entities, monkeypatch):
    class _Orion:
        def __init__(self, *a, **k): pass
        async def query_entities(self, **kw):
            return entities
        async def close(self):
            pass

    monkeypatch.setattr(context_client, "OrionClient", _Orion)
    return await context_client.get_penetrometer_data("parcel1", "tenant1")


@pytest.mark.asyncio
async def test_penetrometer_reads_horizons(monkeypatch):
    entities = [{
        "id": "urn:ngsi-ld:SoilSamplingPoint:1",
        "horizons": [
            {"depthFrom": 0, "depthTo": 30, "penetrationResistance": 2.5},
            {"depthFrom": 30, "depthTo": 60, "penetrationResistance": 4.5},
        ],
    }]
    out = await _run_penetrometer(entities, monkeypatch)
    assert out["available"] is True
    assert out["point_count"] == 2
    assert out["mean_mpa"] == pytest.approx(3.5)
    assert out["max_mpa"] == pytest.approx(4.5)
    assert "0-30" in out["depth_range"] and "30-60" in out["depth_range"]


@pytest.mark.asyncio
async def test_penetrometer_root_fallback_legacy(monkeypatch):
    entities = [{
        "id": "urn:ngsi-ld:SoilSamplingPoint:1",
        "penetrationResistance": {"type": "Property", "value": 3.1},
        "depthFrom": {"type": "Property", "value": 0},
        "depthTo": {"type": "Property", "value": 30},
    }]
    out = await _run_penetrometer(entities, monkeypatch)
    assert out["available"] is True
    assert out["point_count"] == 1
    assert out["mean_mpa"] == pytest.approx(3.1)


@pytest.mark.asyncio
async def test_penetrometer_none_when_no_readings(monkeypatch):
    entities = [{
        "id": "urn:ngsi-ld:SoilSamplingPoint:1",
        "horizons": [{"depthFrom": 0, "depthTo": 30, "ph": 7.2}],
    }]
    out = await _run_penetrometer(entities, monkeypatch)
    assert out is None
