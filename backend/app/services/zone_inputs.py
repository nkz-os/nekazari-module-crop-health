"""Per-zone inputs bundle: zone meteo, daily series and sensors.

Raster-derived inputs (ndvi/sar/soil/twi) stay parcel-level for now and are
marked ``parcel_inherited``.
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
            fidelity={
                "meteo": "zone_specific" if weather else "parcel_inherited",
                "gdd": "zone_specific" if rows else "parcel_inherited",
                "ndvi": "parcel_inherited",
                "sar": "parcel_inherited",
                "soil": "parcel_inherited",
                "twi": "parcel_inherited",
                "balance": "parcel_inherited",
            },
        )
    return out
