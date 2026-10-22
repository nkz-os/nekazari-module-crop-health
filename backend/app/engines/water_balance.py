"""
Water Balance Engine — Dynamic crop water balance.

Implements:
    Balance = Precipitation - (ETo × Kc)

Where Kc (crop coefficient) varies by species and phenological stage.
Optionally adjusts based on real-time soil moisture if available.
"""

from __future__ import annotations

from app.schemas import WaterBalanceResult


def dynamic_water_balance(
    precipitation_mm: float,
    eto_mm: float,
    kc: float,
    soil_moisture_pct: float | None = None,
) -> WaterBalanceResult:
    """Calculate dynamic water balance.

    ETc = ETo × Kc (crop-specific evapotranspiration).
    Balance = Precipitation - ETc.

    If soil_moisture_pct is provided and below stress threshold (15%),
    the effective deficit is amplified by a correction factor to reflect
    that dry soils lose available water faster.

    Args:
        precipitation_mm: Precipitation in mm (current period).
        eto_mm: Reference evapotranspiration in mm.
        kc: Crop coefficient (from bioorchestrator or default).
        soil_moisture_pct: Optional soil moisture (0–100%).

    Returns:
        WaterBalanceResult with deficit flag.
    """
    etc_mm = eto_mm * kc
    balance = precipitation_mm - etc_mm

    # Soil moisture correction: amplify deficit when soil is dry
    if soil_moisture_pct is not None and soil_moisture_pct < 15.0 and balance < 0:
        # Scale factor: 1.0 at 15%, up to 1.5 at 0%
        correction = 1.0 + 0.5 * (1.0 - soil_moisture_pct / 15.0)
        balance *= correction

    return WaterBalanceResult(
        balance_mm=round(balance, 2),
        precip_mm=round(precipitation_mm, 2),
        etc_mm=round(etc_mm, 2),
        kc=kc,
        deficit=balance < 0,
    )
