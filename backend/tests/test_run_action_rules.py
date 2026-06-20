import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api import setup as setup_mod
from app.services import action_rules_io as io


def test_run_action_rules_rejects_without_secret():
    c = TestClient(app)
    r = c.post("/api/crop-health/internal/run-action-rules", json={"tenant_id": "montiko"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_evaluate_parcel_creates_op_when_rule_matches(monkeypatch):
    # plan: one active cover_crop segment in flowering, roller_crimper
    seg = {"id": "urn:ngsi-ld:AgriCrop:montiko:p1:2026:0", "role": "cover_crop", "status": "active",
           "species": "Vicia sativa", "terminationMethod": "roller_crimper",
           "hasAgriParcel": "urn:ngsi-ld:AgriParcel:montiko:p1"}
    async def _plan(p, t): return [seg]
    async def _latest(p, t): return {"phenologyStage": "flowering", "phenologyDeviation": "on_track",
                                     "gddAccumulated": 700.0, "seasonStart": "2025-11-10"}
    async def _stages(sp): return {"flowering": (520.0, 1100.0)}
    async def _ws(p, t=""): return None
    async def _soil(p, t=""): return None
    async def _ndvi(p, t): return None
    async def _rules(species, stage, role, tenant): return [{
        "id": "cover_crop_termination_flowering", "category": "termination", "priority": 10,
        "conditions": {"all": [{"field": "crop.role", "op": "eq", "value": "cover_crop"},
                               {"field": "phenology.current_stage", "op": "eq", "value": "flowering"}]},
        "action": {"operation_type": "tillage", "urgency": "high", "window_days": 7,
                   "description_template": "Tumbar {crop.species}"}}]
    async def _exists(p, rid, today, t): return False
    created = []
    async def _create(p, s, rule, ctx, t, today): created.append(rule["id"]); return "op-1"

    monkeypatch.setattr(io, "_read_crop_plan", _plan)
    monkeypatch.setattr(io, "_read_latest_assessment", _latest, raising=False)
    monkeypatch.setattr(io, "get_phenology_stages", _stages, raising=False)
    monkeypatch.setattr(io, "get_weather_snapshot", _ws, raising=False)
    monkeypatch.setattr(io, "get_soil_properties", _soil, raising=False)
    monkeypatch.setattr(io, "_fetch_parcel_ndvi", _ndvi, raising=False)
    monkeypatch.setattr(io, "get_action_rules", _rules)
    monkeypatch.setattr(io, "_operation_exists", _exists)
    monkeypatch.setattr(io, "_create_operation", _create)

    await io.evaluate_parcel("urn:ngsi-ld:AgriParcel:montiko:p1", "montiko")
    assert created == ["cover_crop_termination_flowering"]


import asyncio
from scripts import cron_action_rules as driver


def test_driver_calls_endpoint_per_tenant(monkeypatch):
    seen = []
    async def _post(tenant, base_url, secret):
        seen.append(tenant); return {"parcels": 1, "operations_created": 1, "errors": []}
    monkeypatch.setattr(driver, "_post_tenant", _post)
    monkeypatch.setenv("ACTION_RULE_TENANTS", "montiko,allotarra")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s")
    asyncio.run(driver.main())
    assert seen == ["montiko", "allotarra"]
