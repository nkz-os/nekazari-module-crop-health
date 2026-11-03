"""Missing relative humidity is never replaced by a default: no VPD, no CWSI."""
from __future__ import annotations

import types

import pytest

from app.schemas import MetricType, SoilProperties
from app.services import pipeline
from app.services.parcel_link import OPEN_FIELD
from app.services.redis_state import ParcelReading
from tests.test_pipeline_under_panel_stress import NOW, _setup
from tests.test_under_panel_sensor_gating import DEVICE, GateRedis, _owner, _run

SOIL = SoilProperties(has_data=True, hydraulics_from_soil=True, field_capacity=0.30, wilting_point=0.12)


def _meteo(rh):
    return types.SimpleNamespace(air_temp_c=24.0, rh_pct=rh, et0_mm=5.0)


def test_missing_rh_stays_none():
    snap = pipeline._snapshot_from_meteo(_meteo(None))
    assert snap is not None
    assert snap.humidity_pct is None


def test_present_rh_is_kept():
    assert pipeline._snapshot_from_meteo(_meteo(63.0)).humidity_pct == 63.0


@pytest.mark.asyncio
async def test_no_cwsi_without_rh(monkeypatch):
    published, _ = _setup(monkeypatch, soil=SOIL, wm={"air_temp_c": 24.0, "et0_mm": 5.0})

    async def _params(*a, **k):
        return types.SimpleNamespace(
            stage="vegetative", kc=0.8, mds_ref=100.0, ky=0.45, d1=-2.0, d2=2.0)

    monkeypatch.setattr(pipeline, "get_phenology_params", _params, raising=False)

    async def _lst(*a, **k):
        return 30.0, "2026-07-15"

    monkeypatch.setattr(pipeline, "_fetch_parcel_lst_with_date", _lst, raising=False)
    _owner(monkeypatch, OPEN_FIELD)
    redis = GateRedis(window={"leafTemperature": [ParcelReading(DEVICE, NOW - 60, 30.0, "CEL")]})
    await _run(MetricType.LEAF_TEMPERATURE, redis)
    assert published["assessments"][-1].cwsi is None
