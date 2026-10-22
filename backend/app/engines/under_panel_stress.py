"""Shade-aware water stress under agrivoltaic panels."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from app.schemas import SoilProperties
from app.services.redis_state import ParcelReading

logger = logging.getLogger(__name__)

# Global horizontal irradiance (W/m2) to open-sky PAR (umol/m2/s):
# ~0.45 PAR fraction x 4.57 umol/J (general-knowledge conversion factor).
PAR_PER_GHI = 2.02
# Below this GHI (night, dawn, dusk) the open-sky reference is meaningless.
MIN_GHI_WM2 = 50.0

MAX_READING_AGE_S = 3600.0
MAX_FUTURE_SKEW_S = 300.0
MAX_THETA = 0.6

FIDELITY_IOT = "iot_sensor"
FIDELITY_PROXY = "regional_proxy"
FIDELITY_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class WaterStress:
    index: float | None
    fidelity: str
    observed_at: datetime | None
    shade_fraction: float | None


def volumetric_soil_moisture(value: float, unit_code: str | None) -> float | None:
    """Volumetric water content (fraction) from a reading; only unitCode P1 (%) is accepted."""
    if unit_code != "P1" or not math.isfinite(value):
        return None
    theta = value / 100.0
    if 0.0 <= theta <= MAX_THETA:
        return theta
    return None


def ks_from_theta(theta: float, fc: float, wp: float, p: float) -> float:
    """FAO-56 water stress coefficient Ks from volumetric moisture."""
    if not all(math.isfinite(x) for x in (theta, fc, wp, p)):
        raise ValueError("non-finite input")
    if not 0.0 <= p < 1.0:
        raise ValueError("depletion fraction p must be in [0, 1)")
    taw = fc - wp
    if taw <= 0:
        raise ValueError("field capacity must exceed wilting point")
    dr = max(0.0, fc - theta)
    raw = p * taw
    if dr <= raw:
        return 1.0
    return max(0.0, (taw - dr) / (taw - raw))


def par_open_from_ghi(ghi_wm2: float) -> float | None:
    """Open-sky PAR (umol/m2/s) from GHI (W/m2): ghi x 2.02 (0.45 PAR fraction x 4.57 umol/J).

    General-knowledge conversion. None for non-finite GHI or below 50 W/m2 (night/dawn).
    """
    if not math.isfinite(ghi_wm2) or ghi_wm2 < MIN_GHI_WM2:
        return None
    return ghi_wm2 * PAR_PER_GHI


def shade_corrected_etc(
    et0_mm: float, kc: float, shade_fraction: float | None, radiative_fraction: float
) -> float:
    """ETc reduced by the radiative share of the shaded fraction."""
    if shade_fraction is None:
        return et0_mm * kc
    return et0_mm * kc * (1.0 - radiative_fraction * shade_fraction)


def _model_index(model_ks: float | None) -> float | None:
    if model_ks is None or not math.isfinite(model_ks) or not 0.0 <= model_ks <= 1.0:
        return None
    return round(1.0 - model_ks, 3)


def compute_water_stress(
    readings: list[ParcelReading],
    soil: SoilProperties,
    p: float,
    model_ks: float | None,
    model_fidelity: str,
    now: datetime,
    shade_fraction: float | None,
) -> WaterStress:
    now_ts = now.timestamp()
    used: list[tuple[float, float]] = []  # (ts, theta)
    for r in readings:
        age = now_ts - r.ts
        if age > MAX_READING_AGE_S or age < -MAX_FUTURE_SKEW_S:
            continue
        theta = volumetric_soil_moisture(r.value, r.unit_code)
        if theta is not None:
            used.append((r.ts, theta))

    if used:
        mean_theta = sum(t for _, t in used) / len(used)
        try:
            ks = ks_from_theta(mean_theta, soil.field_capacity, soil.wilting_point, p)
        except ValueError:
            logger.warning("under_panel_stress: invalid soil/p inputs; using model path")
        else:
            index = round(1.0 - ks, 3)
            if not math.isfinite(index):
                logger.warning("under_panel_stress: non-finite index; using model path")
                return _model_result(model_ks, model_fidelity, now, shade_fraction)
            oldest = min(ts for ts, _ in used)
            observed = datetime.fromtimestamp(min(oldest, now_ts), tz=timezone.utc)
            return WaterStress(
                index,
                FIDELITY_IOT if soil.has_data else FIDELITY_PROXY,
                observed,
                shade_fraction,
            )

    return _model_result(model_ks, model_fidelity, now, shade_fraction)


def _model_result(
    model_ks: float | None, model_fidelity: str, now: datetime, shade_fraction: float | None
) -> WaterStress:
    index = _model_index(model_ks)
    if index is not None:
        return WaterStress(index, model_fidelity, now, shade_fraction)
    return WaterStress(None, FIDELITY_UNAVAILABLE, None, shade_fraction)
