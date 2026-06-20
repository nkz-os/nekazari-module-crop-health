import pytest
from app.services import pipeline


@pytest.mark.asyncio
async def test_returns_none_when_no_crop(monkeypatch):
    async def _read_crop(parcel_id, tenant_id):
        return None  # no hasAgriCrop

    monkeypatch.setattr(pipeline, "_read_assigned_crop", _read_crop, raising=False)
    out = await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t")
    assert out is None


@pytest.mark.asyncio
async def test_sets_stage_from_gdd_and_writes(monkeypatch):
    async def _read_crop(parcel_id, tenant_id):
        return {"species": "Zea mays", "plantingDate": "2026-04-15", "variety": "MAS 26 T"}

    async def _stages(species):
        from app.schemas import StageTable
        return StageTable(stages={
            "emergence": (0.0, 90.0),
            "vegetative": (90.0, 520.0),
            "flowering": (520.0, 1100.0),
            "maturity": (1100.0, 1600.0),
        })

    async def _gdd(tenant, season_start, parcel_id, base_temp=10.0, upper_cutoff=None):
        return {"gdd_total": 300.0, "mean_daily_gdd": 10.0}

    written = {}

    async def _write(entity, tenant_id):
        written["entity"] = entity

    monkeypatch.setattr(pipeline, "_read_assigned_crop", _read_crop, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_phenology_stages", _stages)
    monkeypatch.setattr(pipeline, "_fetch_gdd", _gdd, raising=False)
    monkeypatch.setattr(pipeline, "_publish_assessment", _write, raising=False)

    out = await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t")
    assert out is not None
    assert out.phenology_stage == "vegetative"  # derived from gdd=300
    assert written  # an entity was published to Orion
