import pytest
from app.services import pipeline
from app.services import context_client


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


@pytest.mark.asyncio
async def test_compute_assessment_surfaces_soil_suitability(monkeypatch):
    """Scheduled path must attach the soil-suitability verdict to the rollup."""

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

    async def _write(entity, tenant_id):
        pass

    # Sentinel context with a marginal verdict (real schema type — its
    # None-default fields let to_ngsi_ld serialize without AttributeError)
    from app.schemas import SoilSuitability

    class _Soil:
        suitability = SoilSuitability(verdict="marginal", reason="pH out of range")

    class _SentinelCtx:
        soil = _Soil()

    sentinel_ctx = _SentinelCtx()

    async def _get_crop_ctx(parcel_id, tenant_id="", gdd=None):
        return sentinel_ctx

    attach_calls: list = []
    _real_attach = pipeline.attach_soil_suitability

    def _spy_attach(assessment, crop_context):
        attach_calls.append((assessment, crop_context))
        _real_attach(assessment, crop_context)

    monkeypatch.setattr(pipeline, "_read_assigned_crop", _read_crop, raising=False)
    monkeypatch.setattr(pipeline.context_client, "get_phenology_stages", _stages)
    monkeypatch.setattr(pipeline, "_fetch_gdd", _gdd, raising=False)
    monkeypatch.setattr(pipeline, "_publish_assessment", _write, raising=False)
    monkeypatch.setattr(context_client, "get_crop_context", _get_crop_ctx)
    monkeypatch.setattr(pipeline, "attach_soil_suitability", _spy_attach)

    out = await pipeline.compute_assessment("urn:ngsi-ld:AgriParcel:t:p1", "t")

    assert out is not None
    assert len(attach_calls) == 1, "attach_soil_suitability must be called exactly once"
    _, ctx = attach_calls[0]
    assert ctx is sentinel_ctx, "must be called with the fetched crop context"
    assert out.soil_suitability is not None
    assert out.soil_suitability.verdict == "marginal"
