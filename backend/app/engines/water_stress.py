"""
Water Stress Engine — VPD and CWSI calculations.

Implements:
- Saturation vapor pressure: es(T) = 0.6108 × exp(17.27T / (T+237.3))
- Vapor Pressure Deficit: VPD = es(Ta) - ea
- Crop Water Stress Index: CWSI = ((Tc-Ta) - D1) / (D2 - D1)

References:
- Allen et al., FAO-56 (1998) for es formula
- Idso et al. (1981) for CWSI formulation
"""

from __future__ import annotations

import math

from app.schemas import CWSIResult


def saturation_vapor_pressure(temp_c: float) -> float:
    """Saturation vapor pressure at temperature T (kPa).

    Tetens formula (FAO-56):
        es(T) = 0.6108 × exp(17.27 × T / (T + 237.3))

    Args:
        temp_c: Air temperature in °C.

    Returns:
        Saturation vapor pressure in kPa.
    """
    return 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))


def vapor_pressure_deficit(temp_air: float, humidity_pct: float) -> float:
    """Vapor Pressure Deficit (kPa).

    VPD = es(Ta) - ea
    ea = es(Ta) × (RH/100)

    Args:
        temp_air: Air temperature in °C.
        humidity_pct: Relative humidity (0–100%).

    Returns:
        VPD in kPa.  Always >= 0.

    Raises:
        ValueError: If humidity not in [0, 100].
    """
    if not (0 <= humidity_pct <= 100):
        raise ValueError(f"humidity_pct must be 0–100, got {humidity_pct}")
    es = saturation_vapor_pressure(temp_air)
    ea = es * (humidity_pct / 100.0)
    return max(es - ea, 0.0)


def cwsi(
    temp_canopy: float,
    temp_air: float,
    d1: float,
    d2: float,
) -> CWSIResult:
    """Crop Water Stress Index.

    CWSI = ((Tc - Ta) - D1) / (D2 - D1)

    Where:
        Tc = canopy temperature (sensor IR)
        Ta = air temperature (weather)
        D1 = NWSB (non-water-stressed baseline) — species and stage dependent
        D2 = maximum stress baseline — species and stage dependent

    Result is clamped to [0.0, 1.0].

    Args:
        temp_canopy: Canopy temperature °C (from IR sensor).
        temp_air: Air temperature °C (from weather data).
        d1: Non-water-stressed baseline (NWSB) in °C.
        d2: Maximum stress baseline in °C.  Must differ from d1.

    Returns:
        CWSIResult with CWSI value, VPD, and input parameters.

    Raises:
        ValueError: If d1 == d2 (division by zero).
    """
    if d2 == d1:
        raise ValueError(f"d2 must differ from d1 to avoid division by zero (d1={d1}, d2={d2})")

    diff = temp_canopy - temp_air
    raw = (diff - d1) / (d2 - d1)
    clamped = max(0.0, min(1.0, raw))

    # VPD placeholder — filled by pipeline when humidity is available
    vpd = 0.0

    return CWSIResult(
        cwsi=round(clamped, 4),
        vpd_kpa=vpd,
        temp_canopy=temp_canopy,
        temp_air=temp_air,
        d1=d1,
        d2=d2,
    )


def cwsi_with_weather(
    temp_canopy: float,
    temp_air: float,
    humidity_pct: float,
    d1: float,
    d2: float,
) -> CWSIResult:
    """CWSI with VPD computation from weather data.

    Convenience wrapper that also computes VPD.
    """
    vpd = vapor_pressure_deficit(temp_air, humidity_pct)
    result = cwsi(temp_canopy, temp_air, d1, d2)
    # Update VPD in the result
    return CWSIResult(
        cwsi=result.cwsi,
        vpd_kpa=round(vpd, 4),
        temp_canopy=result.temp_canopy,
        temp_air=result.temp_air,
        d1=result.d1,
        d2=result.d2,
    )
