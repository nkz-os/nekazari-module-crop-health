"""Per-zone inputs bundle: zone meteo, daily series and sensors.

Raster-derived inputs (ndvi/sar) stay parcel-level for now and are marked
``parcel_inherited``; soil and TWI come per zone from the soil and hydrology
modules, ``parcel_inherited`` when those have nothing for the zone.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app.services.zonation import (
    Zone,
    consolidate_sensor_readings,
    is_whole_parcel,
    sensors_in_zone,
)

logger = logging.getLogger(__name__)

ZONE_METEO_MAX_AGE = timedelta(hours=36)
_DEFAULT_LOOKBACK_DAYS = 120
# The weather-map daily endpoint refuses wider ranges.
_MAX_DAILY_RANGE_DAYS = 400


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
    # A parcel-inherited answer is the parcel's own value: nothing zone-level to write.
    if not entry or entry.get("fidelity") != "zone_specific":
        return None
    if not any(entry.get(k) is not None for k in _TWI_KEYS):
        return None
    out = {k: entry.get(k) for k in _TWI_KEYS}
    out["wetnessClass"] = wetness_class(entry.get("wetFraction"))
    return out


def _as_date(value) -> date | None:
    """The season start as a date: the resolver returns an ISO string, tests and callers a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _soil_fidelity(entry: dict | None, soil: dict | None) -> str:
    """``zone_specific`` only when the zone answered with both field capacity and wilting point."""
    if not soil or (entry or {}).get("fidelity") != "zone_specific":
        return "parcel_inherited"
    return "zone_specific" if _number(soil.get("fieldCapacity")) and _number(soil.get("wiltingPoint")) else "parcel_inherited"


def _usable_gdd_rows(rows: list[dict]) -> int:
    """Daily rows carrying both temperature extremes (what the GDD delta needs)."""
    return sum(1 for r in rows if _number(r.get("tMin")) and _number(r.get("tMax")))


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

    out: dict[str, ZoneInputs] = {}
    if is_whole_parcel(zones):
        # Whole-parcel mode has no zone to feed: nothing is fetched.
        return out

    today = now.date()
    start = _as_date(season_start) or (today - timedelta(days=_DEFAULT_LOOKBACK_DAYS))
    if (today - start).days > _MAX_DAILY_RANGE_DAYS:
        clipped = today - timedelta(days=_MAX_DAILY_RANGE_DAYS)
        logger.info(
            "gather_zone_inputs: season start %s of %s is over %d days back, asking weather-map from %s",
            start, parcel_short, _MAX_DAILY_RANGE_DAYS, clipped,
        )
        start = clipped

    from app.services import context_client
    fetch_soil = fetch_soil or context_client.get_zone_soil
    fetch_twi = fetch_twi or context_client.get_zone_twi
    results = await asyncio.gather(
        fetch_daily(parcel_id, tenant_id, start, today),
        gather_sensors(parcel_id, tenant_id),
        fetch_soil(parcel_id, tenant_id, zones),
        fetch_twi(parcel_id, tenant_id, zones),
        return_exceptions=True,
    )
    labels = ("daily fetch", "sensors", "zone soil", "zone twi")
    values: list = []
    for label, res in zip(labels, results):
        if isinstance(res, BaseException):
            if not isinstance(res, Exception):
                raise res
            logger.warning("gather_zone_inputs: %s failed for %s: %s", label, parcel_short, res)
            values.append(None)
        else:
            values.append(res)
    daily = values[0] or {}
    sensors = values[1] or []
    soil_by_zone = values[2] or {}
    twi_by_zone = values[3] or {}

    for z in zones:
        rows = list(daily.get(z.zone_id) or [])
        weather = zone_meteo_ctx(z, now)
        in_zone = sensors_in_zone(z, sensors)
        consolidated = consolidate_sensor_readings(in_zone)
        soil = _soil_from_zone(soil_by_zone.get(z.zone_id))
        twi = _twi_from_zone(twi_by_zone.get(z.zone_id))
        out[z.zone_id] = ZoneInputs(
            zone=z,
            devices=in_zone,
            weather=weather,
            weather_daily=rows,
            sensors=consolidated,
            soil=soil,
            twi=twi,
            fidelity={
                "meteo": (
                    "iot_sensor" if consolidated.get("air_temp_c") is not None
                    else "zone_specific" if weather else "parcel_inherited"
                ),
                "gdd": "zone_specific" if _usable_gdd_rows(rows) else "parcel_inherited",
                "ndvi": "parcel_inherited",
                "sar": "parcel_inherited",
                "soil": _soil_fidelity(soil_by_zone.get(z.zone_id), soil),
                "twi": "zone_specific" if twi else "parcel_inherited",
                # Set by the balance step; stays unavailable when no balance exists.
                "balance": "unavailable",
            },
        )
    return out
