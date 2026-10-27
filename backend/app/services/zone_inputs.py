"""Per-zone inputs bundle: zone meteo, daily series and sensors.

Raster-derived inputs (ndvi/sar) stay parcel-level for now and are marked
``parcel_inherited``; soil and TWI come per zone from the soil and hydrology
modules, ``parcel_inherited`` when those have nothing for the zone.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app.services.zonation import Zone, consolidate_sensor_readings, sensors_in_zone

logger = logging.getLogger(__name__)

ZONE_METEO_MAX_AGE = timedelta(hours=36)
_DEFAULT_LOOKBACK_DAYS = 120


@dataclass
class ZoneInputs:
    zone: Zone
    weather: dict
    weather_daily: list[dict]
    sensors: dict
    ndvi: dict | None = None
    sar: dict | None = None
    soil: dict | None = None
    twi: dict | None = None
    fidelity: dict[str, str] = field(default_factory=dict)
    # Raw located sensor items (``device_id``, ``lon``, ``lat``, ...) inside the zone.
    devices: list[dict] = field(default_factory=list)


_SOIL_KEYS = (
    "fieldCapacity", "wiltingPoint", "ksatSaturated", "availableWaterCapacity",
    "hydrologicGroup", "usdaTextureClass", "ph", "sand", "silt", "clay", "organicCarbon",
)
_TWI_KEYS = ("twiMean", "twiP90", "wetFraction", "slopeMean", "flowAccumMax")
WET_FRACTION_DRAINED = 0.1
WET_FRACTION_WET = 0.5


def wetness_class(wet_fraction) -> str | None:
    """``drained`` below 0.1 wet fraction, ``wet`` from 0.5, else ``balanced``."""
    if not isinstance(wet_fraction, (int, float)) or isinstance(wet_fraction, bool):
        return None
    if wet_fraction < WET_FRACTION_DRAINED:
        return "drained"
    if wet_fraction >= WET_FRACTION_WET:
        return "wet"
    return "balanced"


def _soil_from_zone(entry: dict | None) -> dict | None:
    horizon = (entry or {}).get("horizon")
    if not isinstance(horizon, dict) or not horizon:
        return None
    out = {k: horizon.get(k) for k in _SOIL_KEYS}
    out["provider"] = entry.get("provider")
    return out


def _twi_from_zone(entry: dict | None) -> dict | None:
    if not entry or not any(entry.get(k) is not None for k in _TWI_KEYS):
        return None
    out = {k: entry.get(k) for k in _TWI_KEYS}
    out["wetnessClass"] = wetness_class(entry.get("wetFraction"))
    return out


def _fidelity(entry: dict | None) -> str:
    val = (entry or {}).get("fidelity")
    return val if val in ("zone_specific", "parcel_inherited") else "parcel_inherited"


def zone_meteo_ctx(zone: Zone, now: datetime) -> dict:
    """Meteo variables of the zone, or {} when absent or older than 36 h."""
    obs = zone.observed_at
    if obs is None:
        return {}
    # A naive datetime is treated as UTC so the subtraction cannot raise.
    if obs.tzinfo is None:
        obs = obs.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if now - obs > ZONE_METEO_MAX_AGE:
        return {}
    out: dict = {}
    if zone.t_min is not None and zone.t_max is not None:
        out["air_temp_c"] = (zone.t_min + zone.t_max) / 2
    if zone.t_min is not None:
        out["air_temp_min_24h"] = zone.t_min
    if zone.eto is not None:
        out["et0_mm"] = zone.eto
    if zone.solar_radiation_wm2 is not None:
        out["solar_radiation_wm2"] = zone.solar_radiation_wm2
    return out


async def gather_zone_inputs(
    parcel_id: str,
    parcel_short: str,
    tenant_id: str,
    zones: list[Zone],
    season_start: date | None,
    now: datetime,
    *,
    fetch_daily=None,
    gather_sensors=None,
    fetch_soil=None,
    fetch_twi=None,
) -> dict[str, ZoneInputs]:
    """One daily-series request and one sensor query per parcel, split by zone."""
    if fetch_daily is None or gather_sensors is None:
        from app.services import pipeline
        fetch_daily = fetch_daily or pipeline._fetch_zone_daily
        gather_sensors = gather_sensors or pipeline._gather_parcel_sensors

    today = now.date()
    start = season_start or (today - timedelta(days=_DEFAULT_LOOKBACK_DAYS))
    try:
        daily = await fetch_daily(parcel_id, tenant_id, start, today) or {}
    except Exception as exc:  # noqa: BLE001 — fail-safe
        logger.warning("gather_zone_inputs: daily fetch failed for %s: %s", parcel_short, exc)
        daily = {}
    try:
        sensors = await gather_sensors(parcel_id, tenant_id) or []
    except Exception as exc:  # noqa: BLE001 — fail-safe
        logger.warning("gather_zone_inputs: sensors failed for %s: %s", parcel_short, exc)
        sensors = []

    from app.services import context_client
    fetch_soil = fetch_soil or context_client.get_zone_soil
    fetch_twi = fetch_twi or context_client.get_zone_twi
    try:
        soil_by_zone = await fetch_soil(parcel_id, tenant_id, zones) or {}
    except Exception as exc:  # noqa: BLE001 — fail-safe
        logger.warning("gather_zone_inputs: zone soil failed for %s: %s", parcel_short, exc)
        soil_by_zone = {}
    try:
        twi_by_zone = await fetch_twi(parcel_id, tenant_id, zones) or {}
    except Exception as exc:  # noqa: BLE001 — fail-safe
        logger.warning("gather_zone_inputs: zone twi failed for %s: %s", parcel_short, exc)
        twi_by_zone = {}

    out: dict[str, ZoneInputs] = {}
    for z in zones:
        rows = list(daily.get(z.zone_id) or [])
        weather = zone_meteo_ctx(z, now)
        in_zone = sensors_in_zone(z, sensors)
        out[z.zone_id] = ZoneInputs(
            zone=z,
            devices=in_zone,
            weather=weather,
            weather_daily=rows,
            sensors=consolidate_sensor_readings(in_zone),
            soil=_soil_from_zone(soil_by_zone.get(z.zone_id)),
            twi=_twi_from_zone(twi_by_zone.get(z.zone_id)),
            fidelity={
                "meteo": "zone_specific" if weather else "parcel_inherited",
                "gdd": "zone_specific" if rows else "parcel_inherited",
                "ndvi": "parcel_inherited",
                "sar": "parcel_inherited",
                "soil": _fidelity(soil_by_zone.get(z.zone_id)) if _soil_from_zone(soil_by_zone.get(z.zone_id)) else "parcel_inherited",
                "twi": _fidelity(twi_by_zone.get(z.zone_id)) if _twi_from_zone(twi_by_zone.get(z.zone_id)) else "parcel_inherited",
                "balance": "parcel_inherited",
            },
        )
    return out
