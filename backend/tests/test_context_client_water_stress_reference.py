"""get_phenology_params parses the bioorch water_stress_reference and no longer forces the stage."""
import logging

import pytest

from app.schemas import WaterStressReference
from app.services import context_client


class _Resp:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _patch(monkeypatch, body, calls=None):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            if calls is not None:
                calls.append((url, dict(params or {})))
            return _Resp(body)

    monkeypatch.setattr(context_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(context_client.get_settings(), "bioorchestrator_url", "http://bioorch.invalid", raising=False)
    context_client._phenology_cache.clear()


def _reference():
    return {
        "baselines": [{
            "id": "wheat-pre-heading", "cultivar": None, "stages": ["vegetative"],
            "condition": "sunlit", "a0C": 3.38, "a1CPerKpa": -3.25,
            "upper": {"form": "constant", "valueC": 4.0},
            "valid": {"solarHourFrom": 10, "solarHourTo": 16, "vpdKpaMin": 1.0, "clearSky": True},
            "site": "synthetic", "evidence": "primary_read", "sourceId": "src1", "ref": "Table I",
        }],
        "stages": {
            "vegetative": {"waterSensitive": True, "rdiTolerant": False, "sourceIds": ["src1"], "ref": "r"},
            "maturity": {"waterSensitive": False, "rdiTolerant": True, "sourceIds": [], "ref": "r"},
            "flowering": {"waterSensitive": "unknown", "rdiTolerant": False, "sourceIds": [], "ref": "r"},
        },
        "sourceIds": ["src1"],
    }


@pytest.mark.asyncio
async def test_parses_reference(monkeypatch):
    _patch(monkeypatch, {"kc": 1.1, "species": "wheat", "stage": "vegetative", "water_stress_reference": _reference()})
    p = await context_client.get_phenology_params(species="wheat")
    ref = p.water_stress_reference
    assert isinstance(ref, WaterStressReference)
    b = ref.baselines[0]
    assert (b.a0_c, b.a1_c_per_kpa, b.upper.form, b.upper.value_c) == (3.38, -3.25, "constant", 4.0)
    assert b.valid.solar_hour_from == 10 and b.valid.clear_sky is True and b.stages == ["vegetative"]
    assert ref.stages["vegetative"].water_sensitive is True
    assert ref.stages["maturity"].water_sensitive is False
    assert ref.stages["flowering"].water_sensitive == "unknown"
    assert ref.stages["maturity"].rdi_tolerant is True
    assert ref.source_ids == ["src1"]
    assert p.kc == 1.1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate", [
    lambda r: r["baselines"][0].pop("a0C"),
    lambda r: r["baselines"][0]["upper"].update(form="bogus"),
    lambda r: r["baselines"][0].update(a1CPerKpa="steep"),
    lambda r: r["stages"]["vegetative"].update(waterSensitive="yes"),
    lambda r: r["baselines"][0]["upper"].update(form="linear_vpd"),
])
async def test_malformed_reference_is_none_and_warns(monkeypatch, caplog, mutate):
    ref = _reference()
    mutate(ref)
    _patch(monkeypatch, {"kc": 1.1, "species": "wheat", "stage": "vegetative", "water_stress_reference": ref})
    with caplog.at_level(logging.WARNING, logger=context_client.logger.name):
        p = await context_client.get_phenology_params(species="wheat")
    assert p.water_stress_reference is None
    assert p.kc == 1.1 and p.species == "wheat"
    warnings = [r for r in caplog.records if "water_stress_reference" in r.message]
    assert len(warnings) == 1 and "species=wheat" in warnings[0].message


@pytest.mark.asyncio
async def test_non_object_reference_is_none(monkeypatch):
    _patch(monkeypatch, {"species": "wheat", "water_stress_reference": "nope"})
    p = await context_client.get_phenology_params(species="wheat")
    assert p.water_stress_reference is None


@pytest.mark.asyncio
async def test_absent_reference_is_none(monkeypatch, caplog):
    _patch(monkeypatch, {"kc": 1.1, "species": "wheat", "stage": "vegetative"})
    with caplog.at_level(logging.WARNING, logger=context_client.logger.name):
        p = await context_client.get_phenology_params(species="wheat")
    assert p.water_stress_reference is None
    assert not [r for r in caplog.records if "water_stress_reference" in r.message]


@pytest.mark.asyncio
async def test_stage_not_sent_by_default(monkeypatch):
    calls = []
    _patch(monkeypatch, {"species": "wheat"}, calls)
    p = await context_client.get_phenology_params(species="wheat", gdd=500.0)
    assert "stage" not in calls[0][1] and "stage=" not in calls[0][0]
    assert p.stage  # a str even when bioorch echoes no stage
    context_client._phenology_cache.clear()
    await context_client.get_phenology_params(species="wheat", stage="flowering")
    assert calls[1][1]["stage"] == "flowering"


@pytest.mark.asyncio
async def test_cache_key_includes_none_stage(monkeypatch):
    calls = []
    _patch(monkeypatch, {"species": "wheat"}, calls)
    await context_client.get_phenology_params(species="wheat")
    await context_client.get_phenology_params(species="wheat")
    assert len(calls) == 1
    await context_client.get_phenology_params(species="wheat", stage="vegetative")
    assert len(calls) == 2
