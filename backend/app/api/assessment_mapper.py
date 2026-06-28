"""Map Orion CropHealthAssessment entities to API assessment dicts."""

from __future__ import annotations

from typing import Any


def prop_value(entity: dict[str, Any], key: str, default: Any = None) -> Any:
    """Extract value from keyValues or normalized NGSI-LD property."""
    val = entity.get(key, default)
    if isinstance(val, dict) and "value" in val:
        return val.get("value", default)
    return val


def extract_parcel_id(entity: dict[str, Any]) -> str:
    ref = entity.get("hasAgriParcel") or entity.get("refAgriParcel")
    if isinstance(ref, dict):
        obj = ref.get("object", "")
    elif isinstance(ref, str):
        obj = ref
    else:
        return ""
    return obj.replace("urn:ngsi-ld:AgriParcel:", "")


def _soil_stress_level(ratio: float | None) -> str:
    if ratio is None:
        return "none"
    if ratio <= 0.2:
        return "critical"
    if ratio <= 0.35:
        return "high"
    if ratio <= 0.5:
        return "moderate"
    return "none"


def _advisory_suffix(advisory: str | None) -> str:
    if not advisory:
        return "normal_management"
    if advisory.startswith("compaction.advisory."):
        return advisory.split(".", 2)[-1]
    return advisory


def map_entity_to_assessment(entity: dict[str, Any]) -> dict[str, Any]:
    """Build the full API assessment object from an Orion keyValues entity."""
    parcel = extract_parcel_id(entity)
    sw_mm = prop_value(entity, "soilWaterMm")
    awc_mm = prop_value(entity, "soilAWCmm")
    sw_ratio = prop_value(entity, "soilWaterRatio")

    soil_water_balance = None
    if sw_mm is not None or awc_mm is not None:
        stress_level = prop_value(entity, "soilStressLevel") or _soil_stress_level(sw_ratio)
        soil_water_balance = {
            "swMm": sw_mm,
            "awcMm": awc_mm,
            "swRatio": sw_ratio,
            "stressLevel": stress_level,
            "soilMoistureConfidence": prop_value(entity, "soilWaterConfidence", "low"),
            "depletionFractionP": prop_value(entity, "depletionFractionP"),
            "stressCoefficientKs": prop_value(entity, "stressCoefficientKs"),
            "actualETmm": prop_value(entity, "actualETmm"),
            "deepPercolationMm": prop_value(entity, "deepPercolationMm"),
        }

    wl_level = prop_value(entity, "waterloggingRiskLevel")
    waterlogging_risk = None
    if wl_level is not None:
        waterlogging_risk = {
            "riskLevel": wl_level,
            "saturationHours": prop_value(entity, "waterloggingSaturationHours"),
            "excessMm": prop_value(entity, "waterloggingExcessMm"),
            "drainageRateMmH": prop_value(entity, "waterloggingDrainageRateMmH"),
        }

    composite_index = prop_value(entity, "compositeStressIndex")
    composite_stress = None
    if composite_index is not None:
        composite_stress = {
            "index": composite_index,
            "dominantStressor": prop_value(entity, "dominantStressor", "none"),
            "waterContribution": prop_value(entity, "compositeWaterContribution"),
            "thermalContribution": prop_value(entity, "compositeThermalContribution"),
            "vigorContribution": prop_value(entity, "compositeVigorContribution"),
            "stageKy": prop_value(entity, "compositeStageKy"),
        }

    vhi_val = prop_value(entity, "vhi")
    vhi = None
    if vhi_val is not None or prop_value(entity, "vci") is not None:
        vhi = {
            "vhi": vhi_val,
            "vci": prop_value(entity, "vci"),
            "tci": prop_value(entity, "tci"),
            "asiPct": prop_value(entity, "asiPct"),
            "tciSource": prop_value(entity, "tciSource", "none"),
        }

    sar_flooded = prop_value(entity, "sarIsFlooded")
    sar = None
    if sar_flooded is not None or prop_value(entity, "sarSurfaceMoisture") is not None:
        sar = {
            "isFlooded": sar_flooded,
            "floodStage": prop_value(entity, "sarFloodStage", "none"),
            "surfaceMoistureIndex": prop_value(entity, "sarSurfaceMoisture"),
            "waterloggingRisk": prop_value(entity, "sarWaterloggingRisk"),
            "dataFidelity": prop_value(entity, "sarDataFidelity", "modeled_opendata"),
        }

    compaction_level = prop_value(entity, "compactionRiskLevel")
    compaction_risk = None
    if compaction_level is not None:
        advisory_raw = prop_value(entity, "compactionAdvisory")
        compaction_risk = {
            "level": compaction_level,
            "score": prop_value(entity, "compactionRiskScore", 0),
            "susceptibilityScore": prop_value(entity, "compactionSusceptibilityScore", 0),
            "factors": prop_value(entity, "compactionRiskFactors") or [],
            "moistureWarning": prop_value(entity, "compactionMoistureWarning", False),
            "vigorConcern": prop_value(entity, "compactionVigorConcern", False),
            "requiresVerification": prop_value(entity, "compactionRequiresVerification", True),
            "advisory": _advisory_suffix(advisory_raw),
        }

    soil_ph = prop_value(entity, "soilPh")
    soil_ec = prop_value(entity, "soilEC")
    soil_moisture = prop_value(entity, "soilMoisturePct")
    soil_temp = prop_value(entity, "soilTemperatureC")
    soil_sensors = None
    if any(v is not None for v in (soil_ph, soil_ec, soil_moisture, soil_temp)):
        soil_sensors = {
            "ph": soil_ph,
            "ec": soil_ec,
            "moisturePct": soil_moisture,
            "temperatureC": soil_temp,
        }

    has_soil = prop_value(entity, "soilTexture") or prop_value(entity, "soilFieldCapacity")
    soil_properties = None
    if has_soil:
        soil_properties = {
            "sandPct": prop_value(entity, "soilSandPct"),
            "clayPct": prop_value(entity, "soilClayPct"),
            "fieldCapacity": prop_value(entity, "soilFieldCapacity"),
            "wiltingPoint": prop_value(entity, "soilWiltingPoint"),
            "ksatMmH": prop_value(entity, "soilKsatMmH"),
            "scsHydrologicGroup": prop_value(entity, "soilScsGroup"),
            "usdaTextureClass": prop_value(entity, "soilTexture"),
            "source": prop_value(entity, "soilDataSource"),
            "hasData": True,
        }

    return {
        "id": entity.get("id", ""),
        "parcelId": parcel,
        "cwsiValue": prop_value(entity, "cwsiValue"),
        "cwsiDataFidelity": prop_value(entity, "cwsiDataFidelity"),
        "cwsiTempSource": prop_value(entity, "cwsiTempSource"),
        "cwsiLstDate": prop_value(entity, "cwsiLstDate"),
        "temperatureMeta": {
            "kind": prop_value(entity, "lstKind", "land_surface_temperature"),
            "source": prop_value(entity, "cwsiTempSource", "none"),
            "fidelity": prop_value(entity, "cwsiDataFidelity", "unavailable"),
        },
        "mdsValue": prop_value(entity, "mdsValue"),
        "mdsSeverity": prop_value(entity, "mdsSeverity"),
        "waterBalanceDeficit": prop_value(entity, "waterBalanceDeficit"),
        "thermalCondition": prop_value(entity, "thermalCondition"),
        "thermalSeverity": prop_value(entity, "thermalSeverity"),
        "heatStressHours": prop_value(entity, "heatStressHours"),
        "frostHours": prop_value(entity, "frostHours"),
        "thermalDataFidelity": prop_value(entity, "thermalDataFidelity"),
        "vigorIndex": prop_value(entity, "vigorIndex"),
        "vigorCondition": prop_value(entity, "vigorCondition"),
        "growthAnomaly": prop_value(entity, "growthAnomaly"),
        "vigorIndexUsed": prop_value(entity, "vigorIndexUsed"),
        "vigorDataFidelity": prop_value(entity, "vigorDataFidelity"),
        "compositeStressIndex": composite_index,
        "dominantStressor": prop_value(entity, "dominantStressor"),
        "compositeStress": composite_stress,
        "yieldUtilizationPct": prop_value(entity, "yieldUtilizationPct"),
        "yieldGapConfidence": prop_value(entity, "yieldGapConfidence"),
        "predictedYieldKgHa": prop_value(entity, "predictedYieldKgHa"),
        "baselineYieldKgHa": prop_value(entity, "baselineYieldKgHa"),
        "wueStatus": prop_value(entity, "wueStatus"),
        "wueKgM3": prop_value(entity, "wueKgM3"),
        "wueBiomassKg": prop_value(entity, "wueBiomassKg"),
        "wueWaterAppliedMm": prop_value(entity, "wueWaterAppliedMm"),
        "wueTrend": prop_value(entity, "wueTrend"),
        "overallSeverity": prop_value(entity, "overallSeverity", "LOW"),
        "recommendedAction": prop_value(entity, "recommendedAction", "NO_ACTION"),
        "assessedAt": prop_value(entity, "assessedAt", ""),
        "phenologySource": prop_value(entity, "phenologySource", "default"),
        "dataFidelity": prop_value(entity, "dataFidelity"),
        "cropName": prop_value(entity, "cropName"),
        "cropSpecies": prop_value(entity, "cropSpecies"),
        "varietyName": prop_value(entity, "varietyName"),
        "phenologyStage": prop_value(entity, "phenologyStage"),
        "phenologyDeviation": prop_value(entity, "phenologyDeviation"),
        "stageProgressPct": prop_value(entity, "stageProgressPct"),
        "gddAccumulated": prop_value(entity, "gddAccumulated"),
        "soilProperties": soil_properties,
        "soilWaterMm": sw_mm,
        "soilAWCmm": awc_mm,
        "soilWaterRatio": sw_ratio,
        "soilWaterBalance": soil_water_balance,
        "waterloggingRiskLevel": wl_level,
        "waterloggingSaturationHours": prop_value(entity, "waterloggingSaturationHours"),
        "waterloggingRisk": waterlogging_risk,
        "vhi": vhi,
        "sar": sar,
        "compactionRiskLevel": compaction_level,
        "compactionRiskScore": prop_value(entity, "compactionRiskScore"),
        "compactionRiskFactors": prop_value(entity, "compactionRiskFactors"),
        "compactionMoistureWarning": prop_value(entity, "compactionMoistureWarning"),
        "compactionVigorConcern": prop_value(entity, "compactionVigorConcern"),
        "compactionRequiresVerification": prop_value(entity, "compactionRequiresVerification"),
        "compactionRisk": compaction_risk,
        "soilSensors": soil_sensors,
        "species": prop_value(entity, "cropSpecies"),
    }


def dedupe_latest_per_parcel(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_parcel: dict[str, dict[str, Any]] = {}
    for entity in entities:
        pid = extract_parcel_id(entity)
        if not pid:
            continue
        existing = by_parcel.get(pid)
        assessed = prop_value(entity, "assessedAt", "")
        if existing is None or assessed > prop_value(existing, "assessedAt", ""):
            by_parcel[pid] = entity
    return list(by_parcel.values())
