"""
Waterlogging / Anoxia Risk Engine.

Estimates how long excess water (overflow beyond AWC) will saturate
the root zone based on saturated hydraulic conductivity (ksat) and
SCS hydrologic group. Feeds from soil_water_balance excess output.
"""

from __future__ import annotations

from dataclasses import dataclass

# SCS drainage factor: Group A drains fastest, D slowest
SCS_FACTORS = {"A": 1.5, "B": 1.0, "C": 0.5, "D": 0.2}

_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
_CONDITIONS = {
    "LOW": "normal",
    "MEDIUM": "saturated_short",
    "HIGH": "saturated_prolonged",
    "CRITICAL": "anoxia_risk",
}


@dataclass
class WaterloggingRiskResult:
    excess_mm: float = 0.0
    drainage_rate_mm_h: float = 0.0
    saturation_hours: float = 0.0
    risk_level: str = "LOW"
    condition: str = "normal"
    scs_group: str = "B"
    ksat_mm_h: float = 13.0


def waterlogging_risk(
    excess_mm: float,
    ksat_mm_h: float,
    scs_group: str,
    wetness_class: str | None = None,
) -> WaterloggingRiskResult:
    """Calculate waterlogging risk from excess water and soil drainage.

    Args:
        excess_mm: Water that overflowed AWC (mm) — from soil_water_balance.
        ksat_mm_h: Saturated hydraulic conductivity (mm/h).
        scs_group: SCS hydrologic group (A, B, C, D).
        wetness_class: Terrain wetness of the zone (TWI). With excess water,
            ``wet`` raises the level one step (capped at CRITICAL) and
            ``drained`` lowers it one step (floored at LOW); ``None`` or
            ``balanced`` leave it as is.

    Returns:
        WaterloggingRiskResult with saturation hours and risk level.
    """
    if excess_mm <= 0:
        return WaterloggingRiskResult(
            excess_mm=0.0,
            drainage_rate_mm_h=ksat_mm_h,
            saturation_hours=0.0,
            risk_level="LOW",
            condition="normal",
            scs_group=scs_group,
            ksat_mm_h=ksat_mm_h,
        )

    factor = SCS_FACTORS.get(scs_group, 1.0)
    drainage_rate = ksat_mm_h * factor

    if drainage_rate <= 0:
        drainage_rate = 0.01  # safety: prevent division by zero

    saturation_hours = excess_mm / drainage_rate

    # Risk classification
    if saturation_hours < 6:
        risk_level = "LOW"
        condition = "normal"
    elif saturation_hours < 24:
        risk_level = "MEDIUM"
        condition = "saturated_short"
    elif saturation_hours < 48:
        risk_level = "HIGH"
        condition = "saturated_prolonged"
    else:
        risk_level = "CRITICAL"
        condition = "anoxia_risk"

    step = {"wet": 1, "drained": -1}.get(wetness_class or "", 0)
    if step:
        idx = min(max(_LEVELS.index(risk_level) + step, 0), len(_LEVELS) - 1)
        risk_level = _LEVELS[idx]
        condition = _CONDITIONS[risk_level]

    return WaterloggingRiskResult(
        excess_mm=round(excess_mm, 2),
        drainage_rate_mm_h=round(drainage_rate, 2),
        saturation_hours=round(saturation_hours, 1),
        risk_level=risk_level,
        condition=condition,
        scs_group=scs_group,
        ksat_mm_h=ksat_mm_h,
    )
