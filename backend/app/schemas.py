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


# ── CropHealthAssessment (NGSI-LD output entity) ─────────────────────────────


class CropHealthAssessment(BaseModel):
    """Full crop health assessment — maps to NGSI-LD CropHealthAssessment entity."""
    parcel_id: str
    assessed_at: datetime
    cwsi: CWSIResult | None = None
    mds: MDSResult | None = None
    water_balance: WaterBalanceResult | None = None
    overall_severity: Severity = Severity.LOW
    recommended_action: RecommendedAction = RecommendedAction.NO_ACTION
    phenology_source: str = "default"  # "bioorchestrator" or "default"

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
        return entity
