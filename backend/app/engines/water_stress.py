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
import re
from datetime import datetime, timezone

from app.schemas import CWSIResult, CwsiBaseline, WaterStressReference

# Plausible window (degC) for canopy-minus-air temperature baselines (NWSB d1,
# stress limit d2). Values outside it are not temperatures (e.g. stage day
# counts) and must never be fed to the CWSI formula.
CWSI_BASELINE_MIN_C = -5.0
CWSI_BASELINE_MAX_C = 20.0

# Below this VPD the canopy-air temperature difference is too small to tell
# stressed from unstressed canopies, so the method is not applied. Source:
# Gonzalez-Dugo & Zarco-Tejada 2022, Irrig. Sci., doi:10.1007/s00271-022-00819-6
# (2 kPa floor). A baseline's own valid.vpdKpaMin, when higher, wins.
CWSI_MIN_VPD_KPA = 2.0


def cwsi_baselines_plausible(d1: object, d2: object) -> bool:
    """True when d1, d2 are real numbers with MIN <= d1 < d2 <= MAX (degC)."""
    for v in (d1, d2):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return False
    return CWSI_BASELINE_MIN_C <= d1 < d2 <= CWSI_BASELINE_MAX_C


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
    data_fidelity: str = "regional_proxy",
    temp_source: str = "none",
    lst_sensing_date: str | None = None,
) -> CWSIResult:
    """Crop Water Stress Index.

    CWSI = ((Tc - Ta) - D1) / (D2 - D1)

    Where:
        Tc = canopy temperature (sensor IR or satellite LST)
        Ta = air temperature (weather)
        D1 = NWSB (non-water-stressed baseline) — species and stage dependent
        D2 = maximum stress baseline — species and stage dependent

    Result is clamped to [0.0, 1.0].

    Args:
        temp_canopy: Canopy temperature °C (from IR sensor or satellite LST).
        temp_air: Air temperature °C (from weather data).
        d1: Non-water-stressed baseline (NWSB) in °C.
        d2: Maximum stress baseline in °C.  Must differ from d1.
        data_fidelity: iot_canopy | satellite_lst | regional_proxy.
        temp_source: leaf_temperature | satellite_lst | weather_proxy.
        lst_sensing_date: YYYY-MM-DD of Landsat scene (satellite_lst only).

    Returns:
        CWSIResult with CWSI value, VPD, and input parameters.

    Raises:
        ValueError: If d1, d2 are outside the plausible degC window or d1 >= d2.
    """
    if not cwsi_baselines_plausible(d1, d2):
        raise ValueError(
            f"CWSI baselines must satisfy {CWSI_BASELINE_MIN_C} <= d1 < d2 <= "
            f"{CWSI_BASELINE_MAX_C} degC (d1={d1}, d2={d2})"
        )

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
        data_fidelity=data_fidelity,
        temp_source=temp_source,
        lst_sensing_date=lst_sensing_date,
    )


def cwsi_with_weather(
    temp_canopy: float,
    temp_air: float,
    humidity_pct: float,
    d1: float,
    d2: float,
    data_fidelity: str = "regional_proxy",
    temp_source: str = "none",
    lst_sensing_date: str | None = None,
) -> CWSIResult:
    """CWSI with VPD computation from weather data.

    Convenience wrapper that also computes VPD.
    """
    vpd = vapor_pressure_deficit(temp_air, humidity_pct)
    result = cwsi(
        temp_canopy, temp_air, d1, d2,
        data_fidelity=data_fidelity,
        temp_source=temp_source,
        lst_sensing_date=lst_sensing_date,
    )
    # Update VPD in the result
    return CWSIResult(
        cwsi=result.cwsi,
        vpd_kpa=round(vpd, 4),
        temp_canopy=result.temp_canopy,
        temp_air=result.temp_air,
        d1=result.d1,
        d2=result.d2,
        data_fidelity=result.data_fidelity,
        temp_source=result.temp_source,
        lst_sensing_date=result.lst_sensing_date,
    )


# ── CWSI from published VPD-dependent baselines ──────────────────────────────


def _norm(name: str | None) -> str | None:
    """Case-folded name with every run of '-', '_' and whitespace as one space."""
    if not isinstance(name, str):
        return None
    return re.sub(r"[-_\s]+", " ", name).strip().casefold()


def select_baseline(
    ref: WaterStressReference | None,
    stage: str | None,
    cultivar: str | None,
    solar_hour: float | None = None,
) -> CwsiBaseline | None:
    """Pick the baseline: cultivar and stage match, cultivar for all stages, then stage
    match, then ``stages: null``.

    Within a tier, the first row (file order) whose solar-hour window contains
    ``solar_hour`` wins; rows without a window match any hour. With
    ``solar_hour=None`` the window is not considered. A tier with no row valid at
    that hour falls through to the next tier. Cultivar match ignores case and treats
    runs of '-', '_' and spaces as one space.
    """
    if ref is None:
        return None
    cv = _norm(cultivar)
    candidates = [b for b in ref.baselines if b.cultivar is None or _norm(b.cultivar) == cv]
    tiers = (
        [b for b in candidates if cv is not None and _norm(b.cultivar) == cv
         and b.stages is not None and stage is not None and stage in b.stages],
        [b for b in candidates if cv is not None and _norm(b.cultivar) == cv and b.stages is None],
        [b for b in candidates if b.cultivar is None and b.stages is not None
         and stage is not None and stage in b.stages],
        [b for b in candidates if b.cultivar is None and b.stages is None],
    )
    for tier in tiers:
        for b in tier:
            if solar_hour is None or in_solar_window(b, solar_hour):
                return b
    return None


def nwsb_c(b: CwsiBaseline, vpd_kpa: float) -> float:
    """Non-water-stressed baseline (Tc - Ta, degC) = a0 + a1 * VPD."""
    return float(b.a0_c) + float(b.a1_c_per_kpa) * vpd_kpa


def upper_limit_c(b: CwsiBaseline, temp_air_c: float, vpd_kpa: float) -> float | None:
    """Upper limit (Tc - Ta, degC) of a fully stressed canopy.

    Only ``constant`` and ``linear_vpd`` are computed. The Idso 1981 formula was
    not found in any source read, so ``idso1981`` returns None (no CWSI) rather
    than an invented formula.
    """
    u = b.upper
    if u.form == "constant":
        return float(u.value_c)
    if u.form == "linear_vpd":
        return float(u.a0_c) + float(u.a1_c_per_kpa) * vpd_kpa
    return None


def solar_hour(ts_unix: float, longitude_deg: float) -> float:
    """Local solar hour (0-24) = UTC hour + longitude / 15.

    ASSUMPTION: the equation of time is ignored (error under 20 min); confirm
    with the owner before merge.
    """
    utc = datetime.fromtimestamp(ts_unix, tz=timezone.utc)
    utc_h = utc.hour + utc.minute / 60.0 + utc.second / 3600.0
    return (utc_h + longitude_deg / 15.0) % 24.0


# ── Clear sky (FAO-56, Allen et al. 1998, chapter 3) ────────────────────────

# Solar constant, MJ m-2 min-1 (FAO-56 eq. 21/28).
GSC_MJ_M2_MIN = 0.0820
_MJ_PER_HOUR_TO_WM2 = 1e6 / 3600.0
# ASSUMPTION: a reading is "clear sky" when Rs/Rso >= 0.75 (owner to confirm); the
# baselines were measured on cloudless days but their papers give no ratio.
CLEAR_SKY_MIN_RS_RSO = 0.75


def extraterrestrial_radiation_wm2(
    lat_deg: float, lon_deg: float, ts_unix: float, period_h: float = 1.0,
) -> float:
    """Mean extraterrestrial radiation (W/m2) over the period centred on ``ts_unix``.

    FAO-56 eq. 28: Ra = 12*60/pi * Gsc * dr * [(w2 - w1) sin(phi) sin(delta)
    + cos(phi) cos(delta) (sin(w2) - sin(w1))], in MJ m-2 per period, with dr (eq. 23),
    delta (eq. 24), w (eq. 31; clock time in UTC, so Lz = 0 and Lm = longitude west),
    Sc (eq. 32), b (eq. 33), w1/w2 = w -/+ pi*t1/24 (eq. 29, 30). The sun is below the
    horizon when w < -ws or w > ws (ws, eq. 25): Ra = 0.
    ASSUMPTION: w1 and w2 are clamped to [-ws, ws] near sunrise/sunset (FAO-56 only
    sets Ra = 0 outside); it never applies inside a midday CWSI window.
    """
    utc = datetime.fromtimestamp(ts_unix, tz=timezone.utc)
    j = utc.timetuple().tm_yday
    t = utc.hour + utc.minute / 60.0 + utc.second / 3600.0
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * j / 365)  # eq. 23
    delta = 0.409 * math.sin(2 * math.pi * j / 365 - 1.39)  # eq. 24
    b = 2 * math.pi * (j - 81) / 364  # eq. 33
    sc = 0.1645 * math.sin(2 * b) - 0.1255 * math.cos(b) - 0.025 * math.sin(b)  # eq. 32
    lm_west = -lon_deg
    omega = math.pi / 12 * ((t + 0.06667 * (0.0 - lm_west) + sc) - 12)  # eq. 31
    omega = (omega + math.pi) % (2 * math.pi) - math.pi
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))  # eq. 25
    if omega < -ws or omega > ws:
        return 0.0
    w1 = max(-ws, omega - math.pi * period_h / 24)  # eq. 29
    w2 = min(ws, omega + math.pi * period_h / 24)  # eq. 30
    ra_mj = (12 * 60 / math.pi) * GSC_MJ_M2_MIN * dr * (
        (w2 - w1) * math.sin(phi) * math.sin(delta)
        + math.cos(phi) * math.cos(delta) * (math.sin(w2) - math.sin(w1))
    )  # eq. 28
    return max(0.0, ra_mj) * _MJ_PER_HOUR_TO_WM2 / period_h


def clear_sky_radiation_wm2(ra_wm2: float, elevation_m: float = 0.0) -> float:
    """Rso = (0.75 + 2e-5 * z) * Ra (FAO-56 eq. 37), same units as ``ra_wm2``."""
    return (0.75 + 2e-5 * elevation_m) * ra_wm2


def sky_clear(
    rs_wm2: float | None, lat_deg: float, lon_deg: float, ts_unix: float, elevation_m: float = 0.0,
) -> bool | None:
    """True/False from Rs/Rso >= CLEAR_SKY_MIN_RS_RSO; None when it cannot be told.

    ASSUMPTION: an instantaneous Rs reading stands for the mean of the hour centred on it.
    """
    if rs_wm2 is None or isinstance(rs_wm2, bool) or not math.isfinite(rs_wm2) or rs_wm2 < 0:
        return None
    rso = clear_sky_radiation_wm2(
        extraterrestrial_radiation_wm2(lat_deg, lon_deg, ts_unix), elevation_m,
    )
    if rso <= 0:
        return None
    return rs_wm2 / rso >= CLEAR_SKY_MIN_RS_RSO


def in_solar_window(b: CwsiBaseline, hour: float) -> bool:
    """True when ``hour`` is in the half-open window [from, to) (open ends allowed).

    Half-open so adjacent windows (to of one row == from of the next) never overlap.
    """
    lo, hi = b.valid.solar_hour_from, b.valid.solar_hour_to
    if lo is not None and hour < lo:
        return False
    if hi is not None and hour >= hi:
        return False
    return True


def cwsi_from_baseline(
    temp_canopy_c: float,
    temp_air_c: float,
    rh_pct: float,
    b: CwsiBaseline,
    solar_hour: float,
    *,
    data_fidelity: str = "onsite_calibrated",
    temp_source: str = "leaf_temperature",
) -> CWSIResult | None:
    """CWSI = ((Tc - Ta) - NWSB) / (UL - NWSB), clamped to [0, 1].

    None when the reading is outside the baseline's validity (solar-hour window,
    VPD range, VPD below the published minimum) or when UL <= NWSB.
    """
    if not all(math.isfinite(v) for v in (temp_canopy_c, temp_air_c, rh_pct)):
        return None
    if not (0 <= rh_pct <= 100):
        return None
    if not in_solar_window(b, solar_hour):
        return None
    vpd = vapor_pressure_deficit(temp_air_c, rh_pct)
    vpd_min = max(CWSI_MIN_VPD_KPA, b.valid.vpd_kpa_min or 0.0)
    if vpd < vpd_min:
        return None
    if b.valid.vpd_kpa_max is not None and vpd > b.valid.vpd_kpa_max:
        return None
    nwsb = nwsb_c(b, vpd)
    upper = upper_limit_c(b, temp_air_c, vpd)
    if upper is None or upper <= nwsb:
        return None
    raw = ((temp_canopy_c - temp_air_c) - nwsb) / (upper - nwsb)
    if not math.isfinite(raw):
        return None
    return CWSIResult(
        cwsi=round(max(0.0, min(1.0, raw)), 4),
        vpd_kpa=round(vpd, 4),
        temp_canopy=temp_canopy_c,
        temp_air=temp_air_c,
        d1=round(nwsb, 4),
        d2=round(upper, 4),
        data_fidelity=data_fidelity,
        temp_source=temp_source,
        method_ref=b.ref,
        baseline_id=b.id,
        nwsb_c=round(nwsb, 4),
        upper_c=round(upper, 4),
    )
