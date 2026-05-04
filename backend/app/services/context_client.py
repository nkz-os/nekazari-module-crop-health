"""
Context Client — External service integration with caching and circuit breaker.

Connects to:
1. TimescaleDB (weather_observations) — for current weather data
2. BioOrchestrator (Neo4j via REST) — for phenology parameters (D1, D2, Kc, MDS_ref)
   Endpoint: GET /api/graph/phenology-params?species=...&stage=...

Design:
- TTLCache for phenology params (1h) — species data changes very slowly
- Circuit breaker: if bioorchestrator fails, return hardcoded defaults and log warning
- Weather data queried directly from TimescaleDB (weather-worker has no REST API)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from cachetools import TTLCache

from app.config import get_settings
from app.schemas import (
    PhenologyAlternative,
    PhenologyParams,
    PhenologyProvenance,
    WeatherSnapshot,
)

logger = logging.getLogger(__name__)

# ── Phenology cache ──────────────────────────────────────────────────────────
# Key: (species, stage), Value: PhenologyParams
_phenology_cache: TTLCache[tuple[str, str], PhenologyParams] = TTLCache(
    maxsize=128,
    ttl=get_settings().phenology_cache_ttl,
)


# ── Default phenology parameters (fallback) ──────────────────────────────────
# Conservative defaults for generic crop when bioorchestrator unavailable.
_DEFAULT_PARAMS = PhenologyParams(
    d1=2.0,       # NWSB baseline: typical for Mediterranean fruit trees
    d2=8.0,       # Max stress baseline
    kc=0.85,      # Mid-season generic crop coefficient (FAO-56)
    mds_ref=150.0,  # µm — typical olive in vegetative
    species="generic",
    stage="vegetative",
    is_default=True,
)


async def get_phenology_params(
    species: str = "generic",
    stage: str = "vegetative",
    cultivar: str | None = None,
    management: str | None = None,
    gdd: float | None = None,
) -> PhenologyParams:
    """Fetch phenology-dependent parameters from BioOrchestrator.

    Returns hardcoded defaults if:
    - BioOrchestrator is unreachable (circuit breaker)
    - Requested species/stage is not in the graph
    - HTTP error or timeout

    Args:
        species: Crop species name or AGROVOC URI.
        stage: Phenological stage identifier.
        cultivar: Optional cultivar for context-aware matching.
        management: Optional irrigation strategy for context-aware matching.

    Returns:
        PhenologyParams with provenance when available,
        is_default=True when using fallback values.
    """
    cache_key = (species, stage or "", cultivar or "", management or "", str(gdd or ""))
    cached = _phenology_cache.get(cache_key)
    if cached is not None:
        return cached

    settings = get_settings()
    if not settings.bioorchestrator_url:
        logger.warning("BIOORCHESTRATOR_URL not configured — using defaults")
        return _DEFAULT_PARAMS

    url = f"{settings.bioorchestrator_url}/api/graph/phenology-params"
    params: dict[str, str] = {"species": species}
    if stage:
        params["stage"] = stage
    if cultivar:
        params["cultivar"] = cultivar
    if management:
        params["management"] = management
    if gdd is not None:
        params["gdd"] = str(gdd)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                prov = data.get("provenance", {})
                alts = [
                    PhenologyAlternative(
                        kc=a.get("kc"),
                        source_short=a.get("sourceShort"),
                        source_doi=a.get("sourceDoi"),
                        conditions=a.get("conditions"),
                    )
                    for a in (data.get("alternatives") or [])
                ]
                params = PhenologyParams(
                    d1=data.get("d1", _DEFAULT_PARAMS.d1),
                    d2=data.get("d2", _DEFAULT_PARAMS.d2),
                    kc=data.get("kc", _DEFAULT_PARAMS.kc),
                    mds_ref=data.get("mds_ref", _DEFAULT_PARAMS.mds_ref),
                    species=data.get("species", species),
                    stage=data.get("stage", stage),
                    is_default=data.get("is_default", False),
                    scientific_name=data.get("scientific_name"),
                    stage_description=data.get("stage_description"),
                    kc_confidence_interval=data.get("kc_confidence_interval"),
                    d1_confidence_interval=data.get("d1_confidence_interval"),
                    d2_confidence_interval=data.get("d2_confidence_interval"),
                    mds_ref_confidence_interval=data.get("mds_ref_confidence_interval"),
                    cultivar=data.get("cultivar"),
                    management=data.get("management"),
                    climate_zone=data.get("climate_zone"),
                    match_level=data.get("match_level"),
                    stage_gdd_min=data.get("stage_gdd_min"),
                    stage_gdd_max=data.get("stage_gdd_max"),
                    stage_base_temp=data.get("stage_base_temp"),
                    provenance=PhenologyProvenance(
                        doi=prov.get("doi"),
                        short=prov.get("short"),
                        author=prov.get("author"),
                        year=prov.get("year"),
                        institution=prov.get("institution"),
                        method=prov.get("method"),
                        conditions=prov.get("conditions"),
                    ) if prov else None,
                    alternatives=alts,
                )
                _phenology_cache[cache_key] = params
                logger.info(
                    "Phenology params for %s/%s from bioorchestrator (match=%s, source=%s)",
                    species, stage, data.get("match_level"), prov.get("short"),
                )
                return params

            if resp.status_code == 404:
                logger.info(
                    "No phenology data for %s/%s (404) — using defaults", species, stage
                )
            else:
                logger.warning(
                    "BioOrchestrator returned %d for %s/%s — using defaults",
                    resp.status_code, species, stage,
                )

    except httpx.TimeoutException:
        logger.warning("BioOrchestrator timeout for %s/%s — using defaults", species, stage)
    except httpx.ConnectError:
        logger.warning("BioOrchestrator unreachable — using defaults")
    except Exception as exc:
        logger.error("Unexpected error from bioorchestrator: %s", exc)

    # Cache the default too, to avoid hammering a failing service
    _phenology_cache[cache_key] = _DEFAULT_PARAMS
    return _DEFAULT_PARAMS


async def get_weather_snapshot(
    latitude: float,
    longitude: float,
    tenant_id: str,
) -> WeatherSnapshot | None:
    """Get current weather data from the platform Weather API.

    Queries the timeseries-reader /api/weather/current endpoint.
    Falls back to direct DB query if weather_api_url is not configured.
    """
    settings = get_settings()

    # Priority 1: Platform Weather API
    if settings.weather_api_url:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{settings.weather_api_url}/api/weather/current",
                    params={"lat": latitude, "lon": longitude},
                    headers={"X-Tenant-ID": tenant_id},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return WeatherSnapshot(
                        temp_air=float(data.get("temp_avg", 0)),
                        humidity_pct=float(data.get("humidity_avg", 0)),
                        precip_mm=float(data.get("precip_mm", 0)),
                        eto_mm=float(data.get("eto_mm", 0)),
                        radiation_wm2=float(data["solar_rad_w_m2"]) if data.get("solar_rad_w_m2") else None,
                    )
                elif resp.status_code == 404:
                    logger.info("No weather data for tenant %s at (%.2f, %.2f)", tenant_id, latitude, longitude)
                    return None
                else:
                    logger.warning("Weather API returned %d — falling back", resp.status_code)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning("Weather API unreachable: %s — falling back", e)
        except Exception as e:
            logger.error("Weather API error: %s", e)

    # Priority 2: Direct DB (legacy fallback — remove after API proven)
    if settings.weather_db_url:
        try:
            import asyncpg
            conn = await asyncpg.connect(settings.weather_db_url)
            try:
                row = await conn.fetchrow(
                    """
                    SELECT temp_avg AS temp_air,
                           humidity_avg AS humidity_pct,
                           COALESCE(precip_mm, 0) AS precip_mm,
                           COALESCE(eto_mm, 0) AS eto_mm,
                           solar_rad_w_m2 AS radiation_wm2
                    FROM weather_observations
                    WHERE tenant_id = $1
                    ORDER BY observed_at DESC
                    LIMIT 1
                    """,
                    tenant_id,
                )
                if row is None:
                    return None
                return WeatherSnapshot(
                    temp_air=float(row["temp_air"]),
                    humidity_pct=float(row["humidity_pct"]),
                    precip_mm=float(row["precip_mm"]),
                    eto_mm=float(row["eto_mm"]),
                    radiation_wm2=float(row["radiation_wm2"]) if row["radiation_wm2"] else None,
                )
            finally:
                await conn.close()
        except ImportError:
            pass
        except Exception as exc:
            logger.error("Weather DB fallback failed: %s", exc)

    return None


def clear_phenology_cache() -> None:
    """Clear the phenology cache (useful for testing)."""
    _phenology_cache.clear()
