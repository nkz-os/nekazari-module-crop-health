"""Water stress on a rainfed parcel: a state, never an irrigation task."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.api.assessment_mapper import map_entity_to_assessment
from app.engines import water_stress_level as wsl
from app.engines.water_stress_level import WaterStressIndicator
from app.schemas import (
    CropHealthAssessment, RecommendedAction, Severity, SoilWaterBalanceResult,
    WaterBalanceResult, WaterStress,
)
from app.services import parcel_site, pipeline

NOW = datetime(2026, 11, 11, 3, tzinfo=timezone.utc)


def _assessment(level="moderate", regime=None, stage="vegetative", depletion=-22.9, **kw):
    return CropHealthAssessment(
        parcel_id="p-1", assessed_at=NOW, irrigation_regime=regime, phenology_stage=stage,
        water_stress_indicator=WaterStressIndicator(level, "balance", 0.48),
        water_balance=WaterBalanceResult(
            balance_mm=depletion, precip_mm=0.0, etc_mm=1.0, kc=0.3, deficit=True),
        **kw,
    )


# ── the level -> severity table ────────────────────────────────────────────
@pytest.mark.parametrize("level,stage,expected", [
    ("none", "vegetative", "LOW"),
    ("not_needed", "flowering", "LOW"),
    ("mild", "flowering", "MEDIUM"),
    ("moderate", "vegetative", "MEDIUM"),
    ("moderate", "flowering", "MEDIUM"),
    ("high", "vegetative", "MEDIUM"),
    ("high", "emergence", "MEDIUM"),
    ("high", None, "MEDIUM"),
    ("high", "flowering", "HIGH"),
    ("high", "grain_filling", "HIGH"),
    ("high", "fruit_set", "HIGH"),
    ("high", "kernel_fill", "HIGH"),
])
def test_rainfed_severity_table(level, stage, expected):
    assert wsl.severity_name(level, regime="rainfed", stage=stage) == expected


@pytest.mark.parametrize("regime", [None, "irrigated"])
def test_other_regimes_keep_the_level_table(regime):
    got = [wsl.severity_name(lv, regime=regime, stage="flowering")
           for lv in ("none", "not_needed", "mild", "moderate", "high", "no_data")]
    assert got == ["LOW", "LOW", "MEDIUM", "HIGH", "CRITICAL", None]
    assert wsl.severity_name("no_data", regime="rainfed", stage="flowering") is None


# ── severity and action of an assessment ───────────────────────────────────
def test_rainfed_moderate_stress_with_a_depleted_soil_is_a_watch_not_an_irrigation():
    a = _assessment("moderate", "rainfed")
    sev = pipeline._determine_overall_severity(a)
    assert sev == Severity.MEDIUM
    assert pipeline._determine_action(sev, a.irrigation_regime) == RecommendedAction.MONITOR


@pytest.mark.parametrize("regime", [None, "irrigated"])
def test_depletion_in_millimetres_no_longer_sets_the_severity(regime):
    # the level decides; the same soil depletion used to force CRITICAL
    a = _assessment("moderate", regime)
    sev = pipeline._determine_overall_severity(a)
    assert sev == Severity.HIGH
    assert pipeline._determine_action(sev, regime) == RecommendedAction.IRRIGATE_SCHEDULED
    assert pipeline._determine_overall_severity(_assessment("mild", regime, depletion=-40.0)) == Severity.MEDIUM
    assert pipeline._determine_overall_severity(_assessment("no_data", regime, depletion=-40.0)) == Severity.LOW


@pytest.mark.parametrize("severity", list(Severity))
def test_rainfed_never_recommends_irrigation(severity):
    action = pipeline._determine_action(severity, "rainfed")
    assert action == (RecommendedAction.NO_ACTION if severity == Severity.LOW else RecommendedAction.MONITOR)


def test_action_of_other_regimes_is_unchanged():
    for regime in (None, "irrigated"):
        assert [pipeline._determine_action(s, regime) for s in
                (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)] == [
            RecommendedAction.NO_ACTION, RecommendedAction.MONITOR,
            RecommendedAction.IRRIGATE_SCHEDULED, RecommendedAction.IRRIGATE_IMMEDIATE]


def test_rainfed_high_stress_is_high_only_in_a_sensitive_stage():
    assert pipeline._determine_overall_severity(_assessment("high", "rainfed", "flowering")) == Severity.HIGH
    assert pipeline._determine_overall_severity(_assessment("high", "rainfed", "vegetative")) == Severity.MEDIUM


# ── the rollup and the zones re-resolve with the regime ────────────────────
def _ws(index):
    return WaterStress(index=index, fidelity="parcel_weather", observed_at=None, shade_fraction=None)


def test_rollup_refresh_does_not_ratchet_irrigation_back_in():
    rollup = CropHealthAssessment(
        parcel_id="p-1", assessed_at=NOW, irrigation_regime="rainfed", phenology_stage="vegetative",
        water_stress=_ws(0.6),  # Ks 0.4: high
    )
    rollup.overall_severity = pipeline._determine_overall_severity(rollup)
    pipeline._refresh_rollup_level(rollup, None, [rollup])
    assert rollup.water_stress_indicator.level == "high"
    assert rollup.overall_severity == Severity.MEDIUM
    assert rollup.recommended_action == RecommendedAction.MONITOR


def test_zones_take_the_parcel_level_with_the_regime():
    rollup = CropHealthAssessment(parcel_id="p-1", assessed_at=NOW, irrigation_regime="rainfed",
                                  phenology_stage="vegetative", water_stress=_ws(0.6))
    zone = CropHealthAssessment(parcel_id="p-1", assessed_at=NOW, irrigation_regime="rainfed",
                                phenology_stage="vegetative", zone_id="z1",
                                water_stress_indicator=WaterStressIndicator("no_data", "none"))
    pipeline._apply_parcel_balance_to_zones([zone], rollup, None)
    assert zone.water_stress_indicator.level == "high"
    assert (zone.overall_severity, zone.recommended_action) == (Severity.MEDIUM, RecommendedAction.MONITOR)


def test_rollup_keeps_the_regime_of_its_zones():
    zones = [CropHealthAssessment(parcel_id="p-1", assessed_at=NOW, irrigation_regime="rainfed", zone_id=z)
             for z in ("z1", "z2")]
    assert pipeline._aggregate_rollup("p-1", zones).irrigation_regime == "rainfed"


# ── irrigation requirement ─────────────────────────────────────────────────
def _swb(stress="high"):
    return SoilWaterBalanceResult(sw_mm=10.0, awc_mm=40.0, sw_ratio=0.25, deficit_mm=30.0, stress_level=stress)


def test_no_irrigation_requirement_on_rainfed():
    rainfed = CropHealthAssessment(parcel_id="p-1", assessed_at=NOW, irrigation_regime="rainfed",
                                   soil_water_balance=_swb())
    irrigated = CropHealthAssessment(parcel_id="p-1", assessed_at=NOW, irrigation_regime="irrigated",
                                     soil_water_balance=_swb())
    assert pipeline._crop_requirements(rainfed).irrigation_mm is None
    assert pipeline._crop_requirements(rainfed).water_deficit_mm == 30.0
    assert pipeline._crop_requirements(irrigated).irrigation_mm == 30.0


# ── what is written and what the API returns ───────────────────────────────
def test_the_regime_is_written_only_when_known():
    known = CropHealthAssessment(parcel_id="p-1", assessed_at=NOW, irrigation_regime="rainfed")
    assert known.to_ngsi_ld()["irrigationRegime"] == {"type": "Property", "value": "rainfed"}
    assert "irrigationRegime" not in CropHealthAssessment(parcel_id="p-1", assessed_at=NOW).to_ngsi_ld()
    zone = CropHealthAssessment(parcel_id="p-1", assessed_at=NOW, irrigation_regime="rainfed", zone_id="z1")
    assert zone.to_zone_ngsi_ld()["irrigationRegime"]["value"] == "rainfed"


def test_the_api_returns_the_regime():
    base = {"id": "urn:ngsi-ld:CropHealthAssessment:p-1-20261111", "type": "CropHealthAssessment",
            "hasAgriParcel": "urn:ngsi-ld:AgriParcel:p-1", "assessedAt": "2026-11-11T03:00:00+00:00"}
    assert map_entity_to_assessment({**base, "irrigationRegime": "rainfed"})["irrigationRegime"] == "rainfed"
    assert map_entity_to_assessment(base)["irrigationRegime"] is None


# ── the regime reader ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_parcel_regime_reads_the_site_and_never_raises(monkeypatch):
    async def _site(parcel_id, tenant_id):
        return parcel_site.ParcelSite(42.0, -1.6, "rainfed")

    async def _boom(parcel_id, tenant_id):
        raise RuntimeError("broker down")

    monkeypatch.setattr(parcel_site, "resolve_parcel_site", _site)
    assert await parcel_site.parcel_regime("p-1", "tenant-a") == "rainfed"
    monkeypatch.setattr(parcel_site, "resolve_parcel_site", _boom)
    assert await parcel_site.parcel_regime("p-1", "tenant-a") is None


def test_the_zone_api_returns_the_regime():
    from app.api.assessment_mapper import map_entity_to_zone_assessment

    zone = CropHealthAssessment(parcel_id="p-1", assessed_at=NOW, irrigation_regime="rainfed", zone_id="z1")
    assert map_entity_to_zone_assessment(zone.to_zone_ngsi_ld())["irrigationRegime"] == "rainfed"


@pytest.mark.asyncio
async def test_a_stale_irrigation_need_or_regime_is_deleted_from_the_days_entity(monkeypatch):
    """The upsert merges attributes: what today's entity no longer carries must be removed."""
    deletes = []

    class FakeOrion:
        def __init__(self, *a, **k):
            pass

        async def delete_entity_attr(self, entity_id, attr):
            deletes.append(attr)

        async def close(self):
            pass

    monkeypatch.setattr("nkz_platform_sdk.orion.OrionClient", FakeOrion)
    rainfed = CropHealthAssessment(parcel_id="p-1", assessed_at=NOW, irrigation_regime="rainfed").to_ngsi_ld()
    await pipeline._clear_stale_water_stress(rainfed, "tenant-a")
    assert "irrigationMm" in deletes and "irrigationRegime" not in deletes
    deletes.clear()
    unknown = CropHealthAssessment(parcel_id="p-1", assessed_at=NOW).to_ngsi_ld()
    await pipeline._clear_stale_water_stress(unknown, "tenant-a")
    assert "irrigationMm" in deletes and "irrigationRegime" in deletes
