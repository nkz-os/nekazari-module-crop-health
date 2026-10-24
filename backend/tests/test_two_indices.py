"""Open-field and under-panel water stress are published as two indices."""
from __future__ import annotations

import pytest

from app.schemas import SoilProperties
from app.services.parcel_link import OPEN_FIELD, UNDER_PANEL
from tests.test_pipeline_under_panel_stress import (
    ENTITY_ID, NOW, PARCEL, FakeRedis, _entity, _setup, _trigger, soil_reading,
)

SOIL = SoilProperties(has_data=True, hydraulics_from_soil=True, field_capacity=0.30, wilting_point=0.12)
UP_ATTRS = ("underPanelWaterStressIndex", "underPanelWaterStressFidelity", "underPanelWaterStressObservedAt")


class CtxRedis(FakeRedis):
    def __init__(self, by_context=None, **kw):
        super().__init__(**kw)
        self.by_context = by_context or {}

    async def get_parcel_readings(self, tenant, parcel, context, metric, max_age_s, now_ts):
        return [r for r in self.by_context.get((context, metric), []) if 0 <= now_ts - r.ts <= max_age_s]


def _setup2(monkeypatch, **kw):
    # generic crop (p = 0.5)
    return _setup(monkeypatch, soil=SOIL, eppo="ZZZZZ", **kw)


@pytest.mark.asyncio
async def test_under_panel_only(monkeypatch):
    published, _ = _setup2(monkeypatch)
    await _trigger(CtxRedis({(UNDER_PANEL, "soilMoisture"): [soil_reading(16.0)]}))
    e = _entity(published)
    assert e["underPanelWaterStressIndex"]["value"] == 0.556
    assert e["underPanelWaterStressFidelity"]["value"] == "iot_sensor"
    assert e["underPanelWaterStressObservedAt"]["value"]["@type"] == "DateTime"
    assert e["waterStressFidelity"]["value"] != "iot_sensor"


@pytest.mark.asyncio
async def test_open_field_only(monkeypatch):
    published, _ = _setup2(monkeypatch)
    await _trigger(CtxRedis({(OPEN_FIELD, "soilMoisture"): [soil_reading(17.0)]}))
    e = _entity(published)
    assert e["waterStressIndex"]["value"] == 0.444
    assert e["waterStressFidelity"]["value"] == "iot_sensor"
    assert not any(a in e for a in UP_ATTRS)


@pytest.mark.asyncio
async def test_both_contexts(monkeypatch):
    published, _ = _setup2(monkeypatch)
    redis = CtxRedis({
        (UNDER_PANEL, "soilMoisture"): [soil_reading(16.0)],
        (OPEN_FIELD, "soilMoisture"): [soil_reading(17.0)],
    })
    await _trigger(redis)
    e = _entity(published)
    assert e["underPanelWaterStressIndex"]["value"] == 0.556
    assert e["waterStressIndex"]["value"] == 0.444
    swb = published["assessments"][-1].soil_water_balance
    expected = min(max((0.17 - 0.12) * swb.root_depth_mm, 0.0), swb.awc_mm)
    assert redis.soil_water_set == [(PARCEL, pytest.approx(expected))]


@pytest.mark.asyncio
async def test_under_panel_not_assimilated(monkeypatch):
    published, _ = _setup2(monkeypatch)
    redis = CtxRedis({(UNDER_PANEL, "soilMoisture"): [soil_reading(16.0)]})
    await _trigger(redis)
    swb = published["assessments"][-1].soil_water_balance
    assert redis.soil_water_set == [(PARCEL, swb.sw_mm)]


@pytest.mark.asyncio
async def test_zone_entity_has_no_under_panel(monkeypatch):
    published, _ = _setup2(monkeypatch)
    await _trigger(CtxRedis({(UNDER_PANEL, "soilMoisture"): [soil_reading(16.0)]}))
    z = published["assessments"][-1].to_zone_ngsi_ld()
    assert not any(a in z for a in UP_ATTRS)


@pytest.mark.asyncio
async def test_missing_under_panel_attrs_are_cleared(monkeypatch):
    published, _ = _setup2(monkeypatch)
    await _trigger(CtxRedis({(OPEN_FIELD, "soilMoisture"): [soil_reading(17.0)]}))
    deleted = {d[1] for d in published["deletes"]}
    assert set(UP_ATTRS) <= deleted
