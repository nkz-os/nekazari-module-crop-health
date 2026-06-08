"""
Landsat TIRS Client for Land Surface Temperature (LST).

Used as the lowest-fidelity fallback (modeled_opendata) for the TCI engine
when IoT canopy/soil sensors and local weather stations are unavailable.
Queries Copernicus Data Space Ecosystem (CDSE) STAC API for Landsat 8/9
Collection 2 Level-2 Surface Temperature (ST_B10 band).

Returns None gracefully on any failure — the VHI engine falls back to
weather air temperature proxy with tci_source="weather_proxy".
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from cachetools import TTLCache

logger = logging.getLogger(__name__)

CDSE_STAC_URL = "https://catalogue.dataspace.copernicus.eu/stac"

# Cache: (lat_bin, lon_bin) → bool (scene_available), TTL 48h
_scene_cache: TTLCache[tuple[float, float], bool] = TTLCache(
    maxsize=256, ttl=172800
)


class LandsatTirsClient:
    """Client for retrieving Land Surface Temperature from Landsat 8/9."""

    def __init__(self) -> None:
        pass

    async def get_latest_lst(
        self,
        latitude: float,
        longitude: float,
        window_days: int = 16,
    ) -> float | None:
        """Fetch the most recent clear-sky LST for a coordinate.

        Phase 1: Scene detection — checks if a recent Landsat C2L2 scene
        is available. Full pixel extraction (rasterio/GDAL zonal stats)
        is Phase 2. Returns None on any failure; VHI engine falls back
        to weather air temperature.

        Returns:
            Temperature in Celsius, or None.
        """
        if latitude == 0.0 and longitude == 0.0:
            return None  # unresolved coordinates

        cache_key = (round(latitude, 4), round(longitude, 4))
        cached = _scene_cache.get(cache_key)
        if cached is not None:
            return None  # Scene availability cached; pixel extraction is Phase 2

        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=window_days)).strftime("%Y-%m-%dT00:00:00Z")
        end = now.strftime("%Y-%m-%dT23:59:59Z")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{CDSE_STAC_URL}/search",
                    json={
                        "collections": ["landsat-c2l2-sr"],
                        "intersects": {
                            "type": "Point",
                            "coordinates": [longitude, latitude],
                        },
                        "datetime": f"{start}/{end}",
                        "limit": 1,
                        "query": {
                            "platform": {"in": ["landsat-8", "landsat-9"]},
                            "eo:cloud_cover": {"lte": 70},
                        },
                    },
                )
                if resp.status_code != 200:
                    logger.debug(
                        "CDSE STAC returned %d for (%.4f, %.4f)",
                        resp.status_code, latitude, longitude,
                    )
                    _scene_cache[cache_key] = False
                    return None

                data = resp.json()
                features = data.get("features", [])
                if not features:
                    logger.info(
                        "No Landsat C2L2 scenes for (%.4f, %.4f) in %d days",
                        latitude, longitude, window_days,
                    )
                    _scene_cache[cache_key] = False
                    return None

                feature = features[0]
                assets = feature.get("assets", {})
                st_b10 = assets.get("ST_B10")
                if not st_b10:
                    logger.warning("No ST_B10 band in Landsat scene")
                    _scene_cache[cache_key] = False
                    return None

                scene_id = feature.get("id", "unknown")
                scene_date = feature.get("properties", {}).get("datetime", "")
                logger.info(
                    "Landsat LST scene found: %s (%s) — pixel extraction pending Phase 2",
                    scene_id, scene_date,
                )
                _scene_cache[cache_key] = True
                # Phase 2: extract pixel value from ST_B10 GeoTIFF using rasterio
                # For now, signal scene availability; VHI uses weather proxy for TCI value
                return None

        except httpx.TimeoutException:
            logger.debug("CDSE STAC timeout for (%.4f, %.4f)", latitude, longitude)
        except httpx.ConnectError:
            logger.debug("CDSE STAC unreachable — cluster egress restricted")
        except Exception as exc:
            logger.warning("Landsat LST fetch error: %s", exc)

        _scene_cache[cache_key] = False
        return None
