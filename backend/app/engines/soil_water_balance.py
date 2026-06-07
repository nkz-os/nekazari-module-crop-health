"""
Soil-Aware Water Balance Engine (FAO-56 Ks).

Models soil water content as a reservoir with water stress feedback:
    1. Compute Ks from yesterday's depletion (Dr vs RAW)
    2. ETa = Ks × Kc × ETo  (actual ET under stress)
    3. SW_t = min(AWC, max(0, SW_{t-1} + Inflow - ETa))
    4. DP  = max(0, SW_raw - AWC)

Where:
    AWC = TAW = (FC - WP) × root_depth_mm
    RAW = p × AWC  (readily available water, FAO-56 Table 22)
    Dr  = AWC - SW  (root zone depletion)
    Ks  = (AWC - Dr) / (AWC - RAW)  when Dr > RAW, else 1.0

Reference: FAO Irrigation & Drainage Paper 56, Chapter 8.
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
    raw_mm: float = 0.0
    depletion_fraction_p: float = 0.50
    stress_coefficient_ks: float = 1.0
    actual_et_mm: float = 0.0
    deep_percolation_mm: float = 0.0


def soil_water_balance(
    sw_yesterday: float | None,
    precip_mm: float,
    irrigation_mm: float,
    etc_mm: float,
    fc: float,
    wp: float,
    root_depth_mm: float,
    depletion_fraction_p: float = 0.50,
    eto_mm: float | None = None,
    kc: float | None = None,
) -> SoilWaterBalanceResult:
    """Calculate soil water balance with FAO-56 Ks water stress coefficient.

    Args:
        sw_yesterday: Previous soil water content (mm). None triggers cold start.
        precip_mm: Precipitation since last assessment (mm).
        irrigation_mm: Irrigation applied since last assessment (mm).
        etc_mm: Crop evapotranspiration ETc (mm). Used as fallback if eto_mm/kc
                are not provided.
        fc: Field capacity (cm³/cm³).
        wp: Wilting point (cm³/cm³).
        root_depth_mm: Effective root depth (mm).
        depletion_fraction_p: FAO-56 depletion fraction p (0-1). Default 0.50.
        eto_mm: Reference evapotranspiration ETo (mm). When provided with kc,
                enables internal ETc/ETa computation.
        kc: Crop coefficient Kc. Used with eto_mm for ETa = Ks × Kc × ETo.

    Returns:
        SoilWaterBalanceResult with current state, Ks, and stress classification.
    """
    # ── 1. AWC (= TAW) and RAW ───────────────────────────────────────────
    awc_mm = (fc - wp) * root_depth_mm
    if awc_mm <= 0:
        awc_mm = 1.0  # safety: avoid division by zero
        
    raw_mm = depletion_fraction_p * awc_mm

    inflow_mm = precip_mm + irrigation_mm

    # ── 2. Cold start ────────────────────────────────────────────────────
    # Cold start: if no previous SW, assume 50% AWC (conservative)
    if sw_yesterday is None:
        sw_prev = awc_mm * 0.5
        confidence = "low"
    else:
        sw_prev = sw_yesterday
        confidence = "medium"

    dr_prev = awc_mm - sw_prev
    
    # ── 3. Ks from yesterday's depletion (FAO-56 eq. 84) ─────────────────
    # Calculate Ks (Water stress coefficient)
    if dr_prev > raw_mm:
        denominator = awc_mm - raw_mm
        ks = (awc_mm - dr_prev) / denominator if denominator > 0 else 1.0
    else:
        ks = 1.0
    ks = max(0.0, min(1.0, ks))

    # ── 4. ETc and ETa ───────────────────────────────────────────────────
    # Calculate ETa
    if eto_mm is not None and kc is not None:
        actual_et_mm = ks * kc * eto_mm
        base_etc_mm = kc * eto_mm
    else:
        actual_et_mm = ks * etc_mm
        base_etc_mm = etc_mm

    # ── 5. Soil water balance (uses ETa per FAO-56 Ch.8) ─────────────────
    raw_sw = sw_prev + inflow_mm - actual_et_mm
    excess_mm = max(0.0, raw_sw - awc_mm)
    dp_mm = excess_mm
    sw_mm = min(awc_mm, max(0.0, raw_sw))
    sw_ratio = sw_mm / awc_mm if awc_mm > 0 else 0.0
    deficit_mm = awc_mm - sw_mm

    # ── 6. Stress classification (RAW-based thresholds) ──────────────────
    sw_threshold_none = awc_mm - raw_mm
    if sw_mm > sw_threshold_none:
        stress_level = "none"
    elif sw_mm > sw_threshold_none * 0.5:
        stress_level = "moderate"
    elif sw_mm > 0:
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
        etc_mm=round(base_etc_mm, 2),
        root_depth_mm=root_depth_mm,
        stress_level=stress_level,
        soil_moisture_confidence=confidence,
        raw_mm=round(raw_mm, 2),
        depletion_fraction_p=depletion_fraction_p,
        stress_coefficient_ks=round(ks, 3),
        actual_et_mm=round(actual_et_mm, 2),
        deep_percolation_mm=round(dp_mm, 2),
    )
