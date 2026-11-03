"""get_phenology_params: bioorch d1/d2 are accepted as CWSI baselines only when plausible degC."""
import logging

import pytest

from app.services import context_client


class _Resp:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _patch(monkeypatch, body):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            return _Resp(body)

    monkeypatch.setattr(context_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(context_client.get_settings(), "bioorchestrator_url", "http://bioorch.invalid", raising=False)
    context_client._phenology_cache.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("d1,d2", [(105, 180), (None, None), (15, 45)])
async def test_unusable_baselines_use_defaults_and_keep_rest(monkeypatch, caplog, d1, d2):
    _patch(monkeypatch, {"d1": d1, "d2": d2, "kc": 1.15, "mds_ref": 99.0,
                         "species": "wheat", "stage": "mid-season", "is_default": False})
    with caplog.at_level(logging.WARNING, logger=context_client.logger.name):
        p = await context_client.get_phenology_params(species="wheat", stage="mid-season")
    assert (p.d1, p.d2) == (2.0, 8.0)
    assert p.cwsi_baseline_source == "default"
    assert p.kc == 1.15 and p.mds_ref == 99.0 and p.stage == "mid-season"
    assert p.is_default is False
    warnings = [r for r in caplog.records if "CWSI baselines" in r.message]
    assert len(warnings) == 1
    assert "wheat" in warnings[0].message and "mid-season" in warnings[0].message


@pytest.mark.asyncio
async def test_missing_baselines_use_defaults(monkeypatch):
    _patch(monkeypatch, {"kc": 1.15, "species": "wheat", "stage": "mid-season"})
    p = await context_client.get_phenology_params(species="wheat", stage="mid-season")
    assert (p.d1, p.d2, p.kc) == (2.0, 8.0, 1.15)
    assert p.cwsi_baseline_source == "default"


@pytest.mark.asyncio
async def test_celsius_baselines_accepted(monkeypatch, caplog):
    _patch(monkeypatch, {"d1": 2.0, "d2": 7.0, "kc": 1.0, "species": "wheat",
                         "stage": "stem_elongation", "is_default": False})
    with caplog.at_level(logging.WARNING, logger=context_client.logger.name):
        p = await context_client.get_phenology_params(species="wheat", stage="stem_elongation")
    assert (p.d1, p.d2) == (2.0, 7.0)
    assert p.cwsi_baseline_source == "bioorch"
    assert not [r for r in caplog.records if "CWSI baselines" in r.message]
