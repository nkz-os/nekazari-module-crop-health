"""A crop assigned but not sown yet has accumulated no degree-days.

Regression: the season start used to fall back to 1 January for a crop whose
sowing is still planned, which modelled it from January into a late stage.
"""
import pytest

from app.services import pipeline
from app.services.meteo_context import MeteoContext

_STAGE_TABLE = {"emergence": (0.0, 90.0), "vegetative": (90.0, 520.0), "maturity": (520.0, 1600.0)}


@pytest.mark.asyncio
async def test_not_sown_crop_has_zero_gdd_and_first_stage(monkeypatch):
    async def _read_crop(parcel_id, tenant_id):
        return {"species": "Triticum aestivum", "plantingDate": "2026-10-15"}

    async def _stages(species):
        from app.schemas import StageTable
        return StageTable(stages=dict(_STAGE_TABLE))

    async def _no_season(parcel_id, tenant_id):
        return None

    async def _gdd_must_not_run(*a, **k):
        raise AssertionError("no GDD query for a crop that is not sown")

    async def _write(entity, tenant_id):
        return True

    async def _meteo(*args, **kwargs):
        return MeteoContext(dominant_fidelity="unavailable")

    monkeypatch.setattr(pipeline, "_read_assigned_crop", _read_crop, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_phenology_stages", _stages)
    monkeypatch.setattr(pipeline.context_client, "resolve_season_start", _no_season)
    monkeypatch.setattr(pipeline, "_fetch_gdd", _gdd_must_not_run, raising=False)
    monkeypatch.setattr(pipeline, "_publish_assessment", _write, raising=False)
    monkeypatch.setattr(pipeline, "resolve_meteo_context", _meteo, raising=False)

    a = await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t")
    assert a is not None
    assert a.gdd_accumulated == 0.0
    assert a.phenology_stage == "emergence"
    assert a.season_start is None
