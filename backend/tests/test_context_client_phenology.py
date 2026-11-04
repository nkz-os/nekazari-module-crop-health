"""get_phenology_params: bioorch d1/d2 are not read (CWSI uses published baselines only)."""
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
@pytest.mark.parametrize("d1,d2", [(105, 180), (None, None), (2.0, 7.0)])
async def test_bioorch_d1_d2_ignored_rest_kept(monkeypatch, caplog, d1, d2):
    _patch(monkeypatch, {"d1": d1, "d2": d2, "d1_confidence_interval": [1, 3], "kc": 1.15,
                         "mds_ref": 99.0, "species": "wheat", "stage": "mid-season",
                         "is_default": False})
    with caplog.at_level(logging.WARNING, logger=context_client.logger.name):
        p = await context_client.get_phenology_params(species="wheat", stage="mid-season")
    for field in ("d1", "d2", "cwsi_baseline_source", "d1_confidence_interval",
                  "d2_confidence_interval"):
        assert not hasattr(p, field)
    assert p.kc == 1.15 and p.mds_ref == 99.0 and p.stage == "mid-season"
    assert p.is_default is False
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
