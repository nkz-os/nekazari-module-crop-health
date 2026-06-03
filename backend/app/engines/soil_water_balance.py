"""
Soil-Aware Water Balance Engine.

Models soil water content as a reservoir:
    SW_t = min(AWC, max(0, SW_{t-1} + Precip_t + Irrigation_t - ETc_t))

Where AWC = (FC - WP) × root_depth_mm.
Excess water (overflow beyond AWC) feeds the waterlogging risk engine.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SoilWaterBalanceResult:
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


def soil_water_balance(
    sw_yesterday: float | None,
    precip_mm: float,
    irrigation_mm: float,
    etc_mm: float,
    fc: float,
    wp: float,
    root_depth_mm: float,
) -> SoilWaterBalanceResult:
    """Calculate soil water balance with AWC tracking.

    Args:
        sw_yesterday: Previous soil water content (mm). None triggers cold start.
        precip_mm: Precipitation since last assessment (mm).
        irrigation_mm: Irrigation applied since last assessment (mm).
        etc_mm: Crop evapotranspiration since last assessment (mm).
        fc: Field capacity (cm³/cm³).
        wp: Wilting point (cm³/cm³).
        root_depth_mm: Effective root depth (mm).

    Returns:
        SoilWaterBalanceResult with current state and stress classification.
    """
    awc_mm = (fc - wp) * root_depth_mm
    if awc_mm <= 0:
        awc_mm = 1.0  # safety: avoid division by zero

    inflow_mm = precip_mm + irrigation_mm

    # Cold start: if no previous SW, assume 50% AWC (conservative)
    if sw_yesterday is None:
        sw_prev = awc_mm * 0.5
        confidence = "low"
    else:
        sw_prev = sw_yesterday
        confidence = "medium"

    # Soil water balance
    raw_sw = sw_prev + inflow_mm - etc_mm
    excess_mm = max(0.0, raw_sw - awc_mm)
    sw_mm = min(awc_mm, max(0.0, raw_sw))
    sw_ratio = sw_mm / awc_mm if awc_mm > 0 else 0.0
    deficit_mm = awc_mm - sw_mm

    # Stress classification
    if sw_ratio > 0.5:
        stress_level = "none"
    elif sw_ratio > 0.3:
        stress_level = "moderate"
    elif sw_ratio > 0.15:
        stress_level = "high"
    else:
        stress_level = "critical"

    return SoilWaterBalanceResult(
        sw_mm=round(sw_mm, 2),
        awc_mm=round(awc_mm, 2),
        sw_ratio=round(sw_ratio, 3),
        deficit_mm=round(deficit_mm, 2),
        excess_mm=round(excess_mm, 2),
        inflow_mm=round(inflow_mm, 2),
        etc_mm=round(etc_mm, 2),
        root_depth_mm=root_depth_mm,
        stress_level=stress_level,
        soil_moisture_confidence=confidence,
    )
