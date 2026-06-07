"""
Crop Health Module — Pydantic Schemas

Data contracts for inputs, outputs, and intermediate representations.
All NGSI-LD entities follow the Smart Data Models conventions.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────


class Severity(str, enum.Enum):
    """MDS / water stress severity levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecommendedAction(str, enum.Enum):
    """Standardised action recommendations."""
    NO_ACTION = "NO_ACTION"
    MONITOR = "MONITOR"
    IRRIGATE_SCHEDULED = "IRRIGATE_SCHEDULED"
    IRRIGATE_IMMEDIATE = "IRRIGATE_IMMEDIATE"


class MetricType(str, enum.Enum):
    """Sensor metric types this module processes."""
    LEAF_TEMPERATURE = "leafTemperature"
    TRUNK_DIAMETER = "trunkDiameter"
    SOIL_MOISTURE = "soilMoisture"
    SOIL_PH = "soilPh"
    SOIL_EC = "soilEC"
    SOIL_TEMPERATURE = "soilTemp"


# ── Sensor Reading ────────────────────────────────────────────────────────────


class SensorReading(BaseModel):
    """Normalised sensor reading extracted from FIWARE notification."""
    entity_id: str
    metric_type: MetricType
    value: float
    timestamp: datetime
    parcel_id: str | None = None  # resolved from entity relationship


# ── Redis Sliding Window ──────────────────────────────────────────────────────


class TimeseriesPoint(BaseModel):
    """A single timestamped value stored in the Redis sliding window."""
    ts: float  # UNIX timestamp
    value: float


# ── Weather Data ──────────────────────────────────────────────────────────────


class WeatherSnapshot(BaseModel):
    """Subset of weather_observations relevant for crop health."""
    temp_air: float = Field(..., description="Air temperature °C")
    humidity_pct: float = Field(..., description="Relative humidity %")
    precip_mm: float = Field(0.0, description="Precipitation mm")
    eto_mm: float = Field(0.0, description="Reference evapotranspiration mm")
    radiation_wm2: float | None = Field(None, description="Solar radiation W/m²")


# ── Phenology Parameters (from BioOrchestrator or defaults) ──────────────────


class PhenologyProvenance(BaseModel):
    """Scientific provenance of a phenology parameter."""
    doi: str | None = None
    short: str | None = None
    author: str | None = None
    year: int | None = None
    institution: str | None = None
    method: str | None = None
    conditions: str | None = None


class PhenologyAlternative(BaseModel):
    """Alternative parameter value from a different source."""
    kc: float | None = None
    source_short: str | None = None
    source_doi: str | None = None
    conditions: str | None = None


class PhenologyParams(BaseModel):
    """Species- and stage-specific agronomic coefficients with provenance.

    D1/D2: CWSI baselines (crop-specific, stage-dependent).
    Kc: crop coefficient for water balance.
    mds_ref: reference MDS for the species at current stage.

    Confidence intervals and provenance are present when data comes
    from the BioOrchestrator knowledge graph (non-default).
    """
    d1: float = Field(2.0, description="NWSB — non-water-stressed baseline (°C)")
    d2: float = Field(8.0, description="Maximum stress baseline (°C)")
    kc: float = Field(0.85, description="Crop coefficient")
    mds_ref: float = Field(150.0, description="Reference MDS (µm)")
    species: str = "generic"
    stage: str = "vegetative"
    is_default: bool = True  # True if using hardcoded fallbacks

    # Extended fields from BioOrchestrator (v0.2+)
    scientific_name: str | None = None
    stage_description: str | None = None
    kc_confidence_interval: list[float] | None = None
    d1_confidence_interval: list[float] | None = None
    d2_confidence_interval: list[float] | None = None
    mds_ref_confidence_interval: list[float] | None = None
    cultivar: str | None = None
    management: str | None = None
    climate_zone: str | None = None
    match_level: str | None = None
    provenance: PhenologyProvenance | None = None
    alternatives: list[PhenologyAlternative] = Field(default_factory=list)
    stage_gdd_min: float | None = None
    stage_gdd_max: float | None = None
    stage_base_temp: float | None = None


# ── Engine Results ────────────────────────────────────────────────────────────


class CWSIResult(BaseModel):
    """Crop Water Stress Index calculation result."""
    cwsi: float = Field(..., ge=0.0, le=1.0)
    vpd_kpa: float
    temp_canopy: float
    temp_air: float
    d1: float
    d2: float


class MDSResult(BaseModel):
    """Maximum Daily Shrinkage result."""
    mds_um: float = Field(..., description="MDS in micrometers")
    mds_ref: float
    ratio: float  # mds_um / mds_ref
    severity: Severity
    window_max: float
    window_min: float


class WaterBalanceResult(BaseModel):
    """Dynamic water balance result."""
    balance_mm: float
    precip_mm: float
    etc_mm: float  # ETo × Kc
    kc: float
    deficit: bool


# ── Soil Properties ────────────────────────────────────────────────────────


class SoilProperties(BaseModel):
    """Soil physical properties from the soil module."""
    sand_pct: float = 40.0
    clay_pct: float = 20.0
    silt_pct: float = 40.0
    organic_carbon_pct: float = 1.0
    field_capacity: float = 0.27       # cm³/cm³
    wilting_point: float = 0.12        # cm³/cm³
    ksat_mm_h: float = 13.0            # mm/h
    scs_hydrologic_group: str = "B"
    usda_texture_class: str = "loam"
    source: str = "default_modeled"
    has_data: bool = False


class SoilWaterBalanceResult(BaseModel):
    """Soil-aware water balance with AWC tracking (FAO-56 Ks)."""
    sw_mm: float = 0.0
    awc_mm: float = 0.0
    sw_ratio: float = 0.0
    deficit_mm: float = 0.0
    excess_mm: float = 0.0
    inflow_mm: float = 0.0
    etc_mm: float = 0.0
    root_depth_mm: float = 300.0
    stress_level: str = "none"
    soil_moisture_confidence: str = "low"
    # FAO-56 extensions
    raw_mm: float = 0.0
    depletion_fraction_p: float = 0.50
    stress_coefficient_ks: float = 1.0
    actual_et_mm: float = 0.0
    deep_percolation_mm: float = 0.0


class WaterloggingRiskResult(BaseModel):
    """Waterlogging/anoxia risk from excess water vs drainage."""
    excess_mm: float = 0.0
    drainage_rate_mm_h: float = 0.0
    saturation_hours: float = 0.0
    risk_level: str = "LOW"
    condition: str = "normal"
    scs_group: str = "B"
    ksat_mm_h: float = 13.0


# ── Thermal Stress Result ─────────────────────────────────────────────────


class ThermalStressResult(BaseModel):
    """Heat stress and frost risk evaluation result."""
    heat_stress_hours: float = 0.0
    frost_hours: float = 0.0
    condition: str = "no_stress"  # no_stress | heat_warning | heat_stress | frost_warning | frost_damage
    severity: str = "LOW"
    data_fidelity: str = "regional_proxy"


# ── Vigor Result ──────────────────────────────────────────────────────────


class VigorResult(BaseModel):
    """Crop vigor composite index."""
    vigor_index: float = Field(0.0, ge=0.0, le=1.0)
    growth_anomaly: float = 0.0
    index_used: str = "NDVI"
    condition: str = "normal"
    data_fidelity: str = "modeled_opendata"


# ── VHI / ASIS Result ──────────────────────────────────────────────────────


class VHIResult(BaseModel):
    """Vegetation Health Index and components (FAO Cap 6)."""
    vci: float | None = Field(None, ge=0.0, le=100.0)
    tci: float | None = Field(None, ge=0.0, le=100.0)
    vhi: float | None = Field(None, ge=0.0, le=100.0)
    asi_pct: float | None = Field(None, ge=0.0, le=100.0)
    tci_source: str = "none"
    data_fidelity: str = "none"


# ── SAR Moisture & Flood ───────────────────────────────────────────────────


class SARResult(BaseModel):
    """SAR-derived moisture and flood (Sentinel-1)."""
    is_flooded: bool = False
    flood_stage: str = "none"
    surface_moisture_index: float = Field(0.5, ge=0.0, le=1.0)
    waterlogging_risk: str = "low"
    data_fidelity: str = "modeled_opendata"


# ── Composite Stress Result ────────────────────────────────────────────────


class CompositeStressResult(BaseModel):
    """Weighted stress index combining water + thermal + vigor (Ky FAO-33)."""
    composite_index: float = Field(0.0, ge=0.0, le=100.0)
    dominant_stressor: str = "none"
    water_contribution: float = 0.0
    thermal_contribution: float = 0.0
    vigor_contribution: float = 0.0
    stage_ky: float = 0.45
    condition: str = "no_stress"


# ── Yield Gap Result ───────────────────────────────────────────────────────


class YieldGapResult(BaseModel):
    """Yield potential utilization (FAO-33 Doorenbos-Kassam)."""
    yield_utilization_pct: float = Field(100.0, ge=0.0, le=100.0)
    predicted_yield_kg_ha: float | None = None
    baseline_yield_kg_ha: float | None = None
    dominant_loss_stage: str = ""
    confidence: str = "medium"


# ── Phenology Progress Result ─────────────────────────────────────────────


class PhenologyProgressResult(BaseModel):
    """GDD-based phenology progress vs expected curve."""
    gdd_accumulated: float = 0.0
    current_stage: str = ""
    progress_pct: float = 0.0
    days_to_next_stage: float | None = None
    deviation: str = "on_track"


# ── WUE Result ─────────────────────────────────────────────────────────────


class WUEResult(BaseModel):
    """Water Use Efficiency (conditional on irrigation data)."""
    wue_kg_m3: float | None = None
    status: str = "suppressed"  # operational | advisory | suppressed
    trend: str = "stable"


# ── Compaction Risk Result ─────────────────────────────────────────────────


class CompactionRiskResult(BaseModel):
    """Compaction risk assessment — NOT a diagnosis. Field verification required."""
    risk_level: str          # low | moderate | high | very_high
    risk_score: float        # 0-100
    susceptibility_score: float
    contributing_factors: list[str] = []
    moisture_warning: bool = False
    vigor_concern: bool = False
    traffic_exposure: str = "unknown"
    advisory: str            # i18n key
    requires_field_verification: bool = True
    data_fidelity: str = "regional_proxy"


# ── CropHealthAssessment (NGSI-LD output entity) ─────────────────────────────


class CropHealthAssessment(BaseModel):
    """Full crop health assessment — maps to NGSI-LD CropHealthAssessment entity."""
    parcel_id: str
    assessed_at: datetime
    cwsi: CWSIResult | None = None
    mds: MDSResult | None = None
    water_balance: WaterBalanceResult | None = None
    thermal: ThermalStressResult | None = None
    vigor: VigorResult | None = None
    composite_stress: CompositeStressResult | None = None
    yield_gap: YieldGapResult | None = None
    phenology_progress: PhenologyProgressResult | None = None
    wue: WUEResult | None = None
    vhi: VHIResult | None = None
    sar: SARResult | None = None
    compaction_risk: CompactionRiskResult | None = None
    overall_severity: Severity = Severity.LOW
    recommended_action: RecommendedAction = RecommendedAction.NO_ACTION
    phenology_source: str = "default"
    data_fidelity: str = "regional_proxy"  # onsite_calibrated | local_proxy | regional_proxy | modeled_opendata
    soil_ph: float | None = None
    soil_ec: float | None = None
    soil_moisture_pct: float | None = None
    soil_temperature_c: float | None = None
    # ── Phenological context (persisted for historical queries) ──
    crop_species: str | None = None
    crop_name: str | None = None
    variety_name: str | None = None
    phenology_stage: str | None = None
    gdd_accumulated: float | None = None
    kc: float | None = None
    management: str | None = None
    # ── Soil integration fields ──
    soil_water_balance: SoilWaterBalanceResult | None = None
    waterlogging_risk: WaterloggingRiskResult | None = None
    soil_properties: SoilProperties | None = None

    def to_ngsi_ld(self) -> dict[str, Any]:
        """Serialise to NGSI-LD entity payload."""
        date_str = self.assessed_at.strftime("%Y%m%d")
        entity: dict[str, Any] = {
            "id": f"urn:ngsi-ld:CropHealthAssessment:{self.parcel_id}-{date_str}",
            "type": "CropHealthAssessment",
            "refAgriParcel": {
                "type": "Relationship",
                "object": f"urn:ngsi-ld:AgriParcel:{self.parcel_id}",
            },
            "assessedAt": {
                "type": "Property",
                "value": self.assessed_at.isoformat(),
            },
            "overallSeverity": {
                "type": "Property",
                "value": self.overall_severity.value,
            },
            "recommendedAction": {
                "type": "Property",
                "value": self.recommended_action.value,
            },
            "phenologySource": {
                "type": "Property",
                "value": self.phenology_source,
            },
        }
        if self.cwsi:
            entity["cwsiValue"] = {"type": "Property", "value": round(self.cwsi.cwsi, 4)}
            entity["vpdKpa"] = {"type": "Property", "value": round(self.cwsi.vpd_kpa, 4)}
        if self.mds:
            entity["mdsSeverity"] = {"type": "Property", "value": self.mds.severity.value}
            entity["mdsValue"] = {"type": "Property", "value": round(self.mds.mds_um, 2)}
            entity["mdsRatio"] = {"type": "Property", "value": round(self.mds.ratio, 3)}
        if self.water_balance:
            entity["waterBalanceDeficit"] = {
                "type": "Property",
                "value": round(self.water_balance.balance_mm, 2),
                "unitCode": "MMT",
            }
        if self.thermal:
            entity["thermalCondition"] = {"type": "Property", "value": self.thermal.condition}
            entity["thermalSeverity"] = {"type": "Property", "value": self.thermal.severity}
        if self.vigor:
            entity["vigorIndex"] = {"type": "Property", "value": round(self.vigor.vigor_index, 3)}
            entity["vigorCondition"] = {"type": "Property", "value": self.vigor.condition}
            entity["vigorIndexUsed"] = {"type": "Property", "value": self.vigor.index_used}
        if self.composite_stress:
            entity["compositeStressIndex"] = {"type": "Property", "value": self.composite_stress.composite_index}
            entity["dominantStressor"] = {"type": "Property", "value": self.composite_stress.dominant_stressor}
        if self.vhi:
            if self.vhi.vhi is not None:
                entity["vhi"] = {"type": "Property", "value": self.vhi.vhi}
            if self.vhi.vci is not None:
                entity["vci"] = {"type": "Property", "value": self.vhi.vci}
            if self.vhi.tci is not None:
                entity["tci"] = {"type": "Property", "value": self.vhi.tci}
            if self.vhi.asi_pct is not None:
                entity["asiPct"] = {"type": "Property", "value": self.vhi.asi_pct, "unitCode": "P1"}
            entity["tciSource"] = {"type": "Property", "value": self.vhi.tci_source}
        if self.yield_gap:
            entity["yieldUtilizationPct"] = {"type": "Property", "value": self.yield_gap.yield_utilization_pct}
            entity["yieldGapConfidence"] = {"type": "Property", "value": self.yield_gap.confidence}
            if self.yield_gap.predicted_yield_kg_ha is not None:
                entity["predictedYieldKgHa"] = {"type": "Property", "value": self.yield_gap.predicted_yield_kg_ha}
            if self.yield_gap.baseline_yield_kg_ha is not None:
                entity["baselineYieldKgHa"] = {"type": "Property", "value": self.yield_gap.baseline_yield_kg_ha}
        if self.wue:
            entity["wueStatus"] = {"type": "Property", "value": self.wue.status}
            if self.wue.wue_kg_m3 is not None:
                entity["wueKgM3"] = {"type": "Property", "value": self.wue.wue_kg_m3}
            entity["wueBiomassKg"] = {"type": "Property", "value": self.wue.biomass_estimated_kg}
            entity["wueWaterAppliedMm"] = {"type": "Property", "value": self.wue.water_applied_mm}
            entity["wueTrend"] = {"type": "Property", "value": self.wue.trend}
        if self.compaction_risk:
            entity["compactionRiskLevel"] = {"type": "Property", "value": self.compaction_risk.risk_level}
            entity["compactionRiskScore"] = {"type": "Property", "value": self.compaction_risk.risk_score}
            entity["compactionRiskFactors"] = {"type": "Property", "value": self.compaction_risk.contributing_factors}
            entity["compactionMoistureWarning"] = {"type": "Property", "value": self.compaction_risk.moisture_warning}
            entity["compactionVigorConcern"] = {"type": "Property", "value": self.compaction_risk.vigor_concern}
            entity["compactionRequiresVerification"] = {"type": "Property", "value": self.compaction_risk.requires_field_verification}
        if self.sar:
            entity["sarIsFlooded"] = {"type": "Property", "value": self.sar.is_flooded}
            entity["sarFloodStage"] = {"type": "Property", "value": self.sar.flood_stage}
            entity["sarSurfaceMoisture"] = {"type": "Property", "value": self.sar.surface_moisture_index}
            entity["sarWaterloggingRisk"] = {"type": "Property", "value": self.sar.waterlogging_risk}
        entity["dataFidelity"] = {"type": "Property", "value": self.data_fidelity}
        if self.crop_species is not None:
            entity["cropSpecies"] = {"type": "Property", "value": self.crop_species}
        if self.crop_name is not None:
            entity["cropName"] = {"type": "Property", "value": self.crop_name}
        if self.variety_name is not None:
            entity["varietyName"] = {"type": "Property", "value": self.variety_name}
        if self.phenology_stage is not None:
            entity["phenologyStage"] = {"type": "Property", "value": self.phenology_stage}
        if self.gdd_accumulated is not None:
            entity["gddAccumulated"] = {"type": "Property", "value": self.gdd_accumulated, "unitCode": "DD"}
        if self.kc is not None:
            entity["kc"] = {"type": "Property", "value": self.kc}
        if self.management is not None:
            entity["management"] = {"type": "Property", "value": self.management}
        if self.soil_properties and self.soil_properties.has_data:
            sp = self.soil_properties
            entity["soilSandPct"] = {"type": "Property", "value": sp.sand_pct, "unitCode": "P1"}
            entity["soilClayPct"] = {"type": "Property", "value": sp.clay_pct, "unitCode": "P1"}
            entity["soilFieldCapacity"] = {"type": "Property", "value": sp.field_capacity}
            entity["soilWiltingPoint"] = {"type": "Property", "value": sp.wilting_point}
            entity["soilKsatMmH"] = {"type": "Property", "value": sp.ksat_mm_h, "unitCode": "MMH"}
            entity["soilScsGroup"] = {"type": "Property", "value": sp.scs_hydrologic_group}
            entity["soilTexture"] = {"type": "Property", "value": sp.usda_texture_class}
            entity["soilDataSource"] = {"type": "Property", "value": sp.source}
        if self.soil_water_balance:
            swb = self.soil_water_balance
            entity["soilWaterMm"] = {"type": "Property", "value": swb.sw_mm, "unitCode": "MMT"}
            entity["soilAWCmm"] = {"type": "Property", "value": swb.awc_mm, "unitCode": "MMT"}
            entity["soilWaterRatio"] = {"type": "Property", "value": round(swb.sw_ratio, 3)}
            entity["soilWaterConfidence"] = {"type": "Property", "value": swb.soil_moisture_confidence}
            # FAO-56 extensions
            entity["soilRAWmm"] = {"type": "Property", "value": swb.raw_mm, "unitCode": "MMT"}
            entity["stressCoefficientKs"] = {"type": "Property", "value": round(swb.stress_coefficient_ks, 3)}
            entity["actualETmm"] = {"type": "Property", "value": swb.actual_et_mm, "unitCode": "MMT"}
            entity["deepPercolationMm"] = {"type": "Property", "value": swb.deep_percolation_mm, "unitCode": "MMT"}
        if self.waterlogging_risk:
            wlr = self.waterlogging_risk
            entity["waterloggingRiskLevel"] = {"type": "Property", "value": wlr.risk_level}
            entity["waterloggingSaturationHours"] = {"type": "Property", "value": wlr.saturation_hours, "unitCode": "HUR"}
        if self.soil_ph is not None:
            entity["soilPh"] = {"type": "Property", "value": self.soil_ph}
        if self.soil_ec is not None:
            entity["soilEC"] = {"type": "Property", "value": self.soil_ec, "unitCode": "D10"}
        if self.soil_moisture_pct is not None:
            entity["soilMoisturePct"] = {"type": "Property", "value": self.soil_moisture_pct}
        if self.soil_temperature_c is not None:
            entity["soilTemperatureC"] = {"type": "Property", "value": self.soil_temperature_c}
        return entity


# ── AgriCrop (FIWARE Smart Data Model) ─────────────────────────────────────


class AgriCrop(BaseModel):
    """AgriCrop entity — crop planted on a parcel with sowing/harvest metadata.

    Maps to FIWARE Smart Data Model: dataModel.Agrifood/AgriCrop
    """
    parcel_id: str
    season: str | None = None  # e.g. "2025-2026"
    category: str = "sowing"
    planting_date: str | None = None     # ISO date "YYYY-MM-DD"
    harvest_date: str | None = None
    variety: str | None = None
    species: str | None = None
    eppo_code: str | None = None
    seeding_rate_kg_ha: float | None = None
    input_method: str = "pending"        # isobus_automated | mobile_app | manual_web | pending

    def to_ngsi_ld(self) -> dict[str, Any]:
        """Serialise to NGSI-LD entity payload using FIWARE-strict hasAgriParcel."""
        entity_id = f"urn:ngsi-ld:AgriCrop:{self.parcel_id}-{self.season or 'pending'}"
        entity: dict[str, Any] = {
            "id": entity_id,
            "type": "AgriCrop",
            "hasAgriParcel": {
                "type": "Relationship",
                "object": f"urn:ngsi-ld:AgriParcel:{self.parcel_id}",
            },
            "category": {"type": "Property", "value": self.category},
        }
        if self.planting_date is not None:
            entity["plantingDate"] = {"type": "Property", "value": self.planting_date}
        if self.harvest_date is not None:
            entity["harvestDate"] = {"type": "Property", "value": self.harvest_date}
        if self.variety is not None:
            entity["variety"] = {"type": "Property", "value": self.variety}
        if self.species is not None:
            entity["species"] = {"type": "Property", "value": self.species}
        if self.eppo_code is not None:
            entity["eppoCode"] = {"type": "Property", "value": self.eppo_code}
        if self.seeding_rate_kg_ha is not None:
            entity["seedingRate"] = {
                "type": "Property",
                "value": self.seeding_rate_kg_ha,
                "unitCode": "KGM",
            }
        entity["inputMethod"] = {"type": "Property", "value": self.input_method}
        return entity

    @classmethod
    def from_ngsi_ld(cls, entity: dict) -> "AgriCrop":
        """Parse from Orion-LD keyValues response."""
        parcel = ""
        has_parcel = entity.get("hasAgriParcel")
        if isinstance(has_parcel, dict):
            parcel = has_parcel.get("object", "").replace("urn:ngsi-ld:AgriParcel:", "")
        elif isinstance(has_parcel, str):
            parcel = has_parcel.replace("urn:ngsi-ld:AgriParcel:", "")

        entity_id = entity.get("id", "")
        season = entity_id.split(":")[-1] if ":" in entity_id else None

        return cls(
            parcel_id=parcel,
            season=season,
            category=entity.get("category", "sowing"),
            planting_date=entity.get("plantingDate"),
            harvest_date=entity.get("harvestDate"),
            variety=entity.get("variety"),
            species=entity.get("species"),
            eppo_code=entity.get("eppoCode"),
            seeding_rate_kg_ha=entity.get("seedingRate"),
            input_method=entity.get("inputMethod", "pending"),
        )


# ── F4: Crop Context from BioOrchestrator ────────────────────────────────────


class CropInfo(BaseModel):
    eppo: str = "unknown"
    name: str | None = None
    scientific_name: str | None = None


class VarietyInfo(BaseModel):
    name: str | None = None
    uri: str | None = None


class SeasonInfo(BaseModel):
    start: str | None = None
    end: str | None = None
    gdd_accumulated: float | None = None
    current_stage: str | None = None


class PhenologyInfo(BaseModel):
    stage: str | None = None
    stage_gdd_min: float | None = None
    stage_gdd_max: float | None = None
    kc: float | None = None
    ky: float | None = None
    d1: float | None = None
    d2: float | None = None
    mds_ref: float | None = None
    base_temp: float | None = None


class SoilActual(BaseModel):
    ph: float | None = None
    texture: str | None = None
    awc_mm: float | None = None
    organic_matter_pct: float | None = None
    bulk_density_g_cm3: float | None = None
    depth_cm: float | None = None
    source: str = "unavailable"
    data_available: bool = False


class SoilSuitability(BaseModel):
    ph_match: bool = True
    texture_match: bool = True
    awc_sufficient: bool = True
    overall: str = "unknown"
    warnings: list[str] = []


class SoilRequirements(BaseModel):
    ph_min: float | None = None
    ph_max: float | None = None
    textures: list[str] = []
    drainage: str | None = None
    depth_min_cm: float | None = None
    salinity_max_ds_m: float | None = None


class SoilSection(BaseModel):
    requirements: SoilRequirements | None = None
    actual: SoilActual | None = None
    suitability: SoilSuitability | None = None


class SoilSensors(BaseModel):
    available: bool = False
    last_reading: str | None = None
    ph: float | None = None
    ec_ds_m: float | None = None
    moisture_pct: float | None = None
    temperature_c: float | None = None


class CropContext(BaseModel):
    parcel_id: str
    crop: CropInfo = CropInfo()
    variety: VarietyInfo | None = None
    management: str | None = None
    season: SeasonInfo = SeasonInfo()
    phenology: PhenologyInfo | None = None
    thermal_limits: dict | None = None
    soil: SoilSection = SoilSection()
    soil_sensors: SoilSensors | None = None
    phenology_source: str = "default"
    match_level: str = "none"
    provenance: dict | None = None
