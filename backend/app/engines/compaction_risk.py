"""Compaction Risk Engine — contextual advisory, NOT a diagnosis.

Combines soil susceptibility (static, from soil module) with dynamic
factors (soil moisture, multi-year NDVI patterns, optional traffic data)
to produce a risk assessment that guides management decisions.

This engine never claims to detect active compaction — it always
recommends field verification for high-risk zones.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CompactionRiskResult:
    risk_level: str = "low"           # low | moderate | high | very_high
    risk_score: float = 0.0           # 0-100
    susceptibility_score: float = 0.0
    contributing_factors: list[str] = field(default_factory=list)
    moisture_warning: bool = False
    vigor_concern: bool = False
    traffic_exposure: str = "unknown"  # unknown | low | moderate | high
    advisory: str = "compaction.advisory.normal_management"
    requires_field_verification: bool = False
    data_fidelity: str = "regional_proxy"


def evaluate_compaction_risk(
    soil_susceptibility_score: float,
    soil_susceptibility_class: str,
    soil_moisture_pct: float | None = None,
    soil_moisture_stress: str | None = None,
    vigor_anomaly_multiyear: float | None = None,
    vigor_anomaly_years: int = 0,
    traffic_intensity: float | None = None,
    fidelity: str = "regional_proxy",
) -> CompactionRiskResult:
    """Evaluate compaction risk — NOT a diagnosis.

    This engine provides context-aware risk assessment to guide
    management decisions and field verification. It does not claim
    to detect active compaction without ground-truth data.

    Args:
        soil_susceptibility_score: 0-100 from soil module Phase 1.
        soil_susceptibility_class: very_low|low|moderate|high|very_high.
        soil_moisture_pct: Current volumetric moisture % from IoT.
        soil_moisture_stress: Stress level from soil_water_balance engine.
        vigor_anomaly_multiyear: Avg NDVI anomaly over 2+ seasons.
        vigor_anomaly_years: Number of seasons analyzed.
        traffic_intensity: 0-1 from gis-routing (optional).
        fidelity: dataFidelity level.

    Returns:
        CompactionRiskResult with risk level, score, and advisory key.
    """
    factors: list[str] = []
    risk_score = soil_susceptibility_score * 0.50
    moisture_warning = False
    vigor_concern = False

    # ── Soil moisture context ──
    if soil_moisture_pct is not None:
        if soil_moisture_pct > 25.0 and soil_susceptibility_class in ("high", "very_high"):
            moisture_warning = True
            risk_score += 15.0
            factors.append("wet_soil_on_susceptible_ground")
        elif soil_moisture_pct > 25.0:
            risk_score += 5.0
            factors.append("wet_soil")
    elif soil_moisture_stress is not None and soil_moisture_stress == "none":
        # Surplus water condition from soil_water_balance
        if soil_susceptibility_class in ("high", "very_high"):
            moisture_warning = True
            risk_score += 10.0
            factors.append("moist_soil_susceptible")

    # ── Multi-year vigor pattern ──
    if vigor_anomaly_multiyear is not None and vigor_anomaly_years >= 2:
        if vigor_anomaly_multiyear < -0.10:
            vigor_concern = True
            risk_score += 15.0
            factors.append(f"persistent_low_vigor_{vigor_anomaly_years}y")
        elif vigor_anomaly_multiyear < -0.05:
            risk_score += 8.0
            factors.append(f"mild_persistent_low_vigor_{vigor_anomaly_years}y")

    # ── Traffic exposure ──
    if traffic_intensity is not None:
        if traffic_intensity > 0.7:
            risk_score += 12.0
            factors.append("high_traffic_exposure")
            traffic_label = "high"
        elif traffic_intensity > 0.3:
            risk_score += 6.0
            factors.append("moderate_traffic_exposure")
            traffic_label = "moderate"
        else:
            traffic_label = "low"
    else:
        traffic_label = "unknown"

    risk_score = min(100.0, round(risk_score, 1))

    # ── Classification ──
    if risk_score < 30.0:
        level = "low"
    elif risk_score < 50.0:
        level = "moderate"
    elif risk_score < 70.0:
        level = "high"
    else:
        level = "very_high"

    # ── Advisory generation ──
    if moisture_warning:
        advisory = "compaction.advisory.avoid_traffic_wet_soil"
    elif vigor_concern:
        advisory = "compaction.advisory.verify_compaction_field"
    elif level in ("high", "very_high"):
        advisory = "compaction.advisory.monitor_susceptible_soil"
    else:
        advisory = "compaction.advisory.normal_management"

    return CompactionRiskResult(
        risk_level=level,
        risk_score=risk_score,
        susceptibility_score=soil_susceptibility_score,
        contributing_factors=factors,
        moisture_warning=moisture_warning,
        vigor_concern=vigor_concern,
        traffic_exposure=traffic_label,
        advisory=advisory,
        requires_field_verification=vigor_concern or level in ("high", "very_high"),
        data_fidelity=fidelity,
    )
