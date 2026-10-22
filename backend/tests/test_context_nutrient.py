"""Tests for context_client.get_nutrient_recommendation."""
import pytest
from app.services import context_client


@pytest.mark.asyncio
async def test_returns_recommendation_from_bioorch(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {
                "species": "Triticum aestivum",
                "stage": "vegetative",
                "recommendations": [
                    {"element": "nitrogen", "uptake_kg_ha_day": 2.5,
                     "soil_level": 0, "status": "deficient", "action": "Increase nitrogen"},
                ],
            }
    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()
    monkeypatch.setattr(context_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(context_client.get_settings(), "bioorchestrator_url", "http://bio", raising=False)
    rec = await context_client.get_nutrient_recommendation("Triticum aestivum", "vegetative")
    assert rec is not None
    assert rec["species"] == "Triticum aestivum"
    assert len(rec["recommendations"]) == 1


@pytest.mark.asyncio
async def test_returns_none_on_error(monkeypatch):
    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): raise RuntimeError("timeout")
    monkeypatch.setattr(context_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(context_client.get_settings(), "bioorchestrator_url", "http://bio", raising=False)
    rec = await context_client.get_nutrient_recommendation("Triticum aestivum", "vegetative")
    assert rec is None


@pytest.mark.asyncio
async def test_returns_none_when_url_not_set(monkeypatch):
    monkeypatch.setattr(context_client.get_settings(), "bioorchestrator_url", None, raising=False)
    rec = await context_client.get_nutrient_recommendation("Triticum aestivum", "vegetative")
    assert rec is None
