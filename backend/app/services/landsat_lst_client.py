"""
Landsat TIRS Client for Land Surface Temperature (LST).

Used as the lowest-fidelity fallback (modeled_opendata) for the TCI engine
when IoT canopy/soil sensors and local weather stations are unavailable.
Uses Copernicus Data Space Ecosystem (CDSE) STAC API to find Landsat 8/9.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


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
        """
        Fetch the most recent clear-sky LST for a coordinate.
        
        Args:
            latitude: Target latitude
            longitude: Target longitude
            window_days: Days to look back (Landsat revisit is 8-16 days)
            
        Returns:
            Temperature in Celsius if a cloud-free pixel is found, else None.
        """
        # TODO: Implement actual STAC query to CDSE for Collection 2 Level-2 Surface Temperature (ST)
        # 1. Query https://stac.dataspace.copernicus.eu/v1/search
        # 2. Filter collections=["LANDSAT-8", "LANDSAT-9"]
        # 3. Retrieve ST_B10 (Surface Temperature Band 10) and QA_PIXEL (Cloud mask)
        # 4. Apply scale factor (0.00341802 * DN + 149.0 - 273.15) to get Celsius
        logger.info("Landsat TIRS fallback queried for %.4f, %.4f", latitude, longitude)
        return None  # Placeholder until CDSE Landsat ST integration is complete

