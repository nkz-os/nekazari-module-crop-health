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

# Key: (variety, irrigation_regime), Value: float (yieldKgHa)
_yield_baseline_cache: TTLCache[tuple[str, str], float] = TTLCache(
    maxsize=128,
    ttl=86400,  # 24h
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


async def get_variety_yield_baseline(
    variety: str,
    irrigation_regime: str = "rainfed",
) -> float | None:
    """Fetch potential yield from BioOrchestrator's VarietyTrial.
    
    Averages the yieldKgHa for the matching variety and irrigation regime.
    """
    if not variety:
        return None
        
    cache_key = (variety, irrigation_regime)
    if cache_key in _yield_baseline_cache:
        return _yield_baseline_cache[cache_key]

    settings = get_settings()
    if not settings.bioorchestrator_url:
        return None

    url = f"{settings.bioorchestrator_url}/api/graph/agriculture/variety-trials"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params={"variety": variety})
            if resp.status_code == 200:
                trials = resp.json()
                matching_trials = [
                    t for t in trials
                    if t.get("variety") == variety 
                    and t.get("irrigationRegime") == irrigation_regime
                    and t.get("yieldKgHa") is not None
                ]
                if matching_trials:
                    avg_yield = sum(t["yieldKgHa"] for t in matching_trials) / len(matching_trials)
                    _yield_baseline_cache[cache_key] = avg_yield
                    return avg_yield
    except Exception as exc:
        logger.warning("Failed to fetch variety yield baseline: %s", exc)

    return None


def clear_phenology_cache() -> None:
    """Clear the phenology cache (useful for testing)."""
    _phenology_cache.clear()


# ── Soil Properties Client ──────────────────────────────────────────────────

_soil_cache: TTLCache[str, dict] = TTLCache(maxsize=128, ttl=3600)
_coord_cache: TTLCache[str, tuple[float, float]] = TTLCache(maxsize=256, ttl=86400)

_DEFAULT_SOIL_DICT = {
    "sand_pct": 40, "clay_pct": 20, "silt_pct": 40,
    "organic_carbon_pct": 1.0, "field_capacity": 0.27,
    "wilting_point": 0.12, "ksat_mm_h": 13.0,
    "scs_hydrologic_group": "B", "usda_texture_class": "loam",
    "source": "default_modeled", "has_data": False,
}


async def _resolve_parcel_coords(parcel_id: str, tenant_id: str) -> tuple[float, float] | None:
    """Resolve parcel centroid coordinates from Orion-LD AgriParcel."""
    cache_key = f"{tenant_id}:{parcel_id}"
    cached = _coord_cache.get(cache_key)
    if cached:
        return cached

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Accept": "application/ld+json"}
            if tenant_id:
                headers["NGSILD-Tenant"] = tenant_id
            resp = await client.get(
                f"{settings.orion_ld_url}/ngsi-ld/v1/entities/urn:ngsi-ld:AgriParcel:{parcel_id}",
                params={"options": "keyValues"},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                loc = data.get("location")
                if isinstance(loc, dict) and loc.get("type") == "Point":
                    coords = loc["coordinates"]
                    result = (coords[1], coords[0])  # lat, lon
                    _coord_cache[cache_key] = result
                    return result
                elif isinstance(loc, dict) and loc.get("type") == "Polygon":
                    ring = loc.get("coordinates", [[[]]])[0]
                    if ring:
                        lats = [p[1] for p in ring]
                        lons = [p[0] for p in ring]
                        result = (sum(lats) / len(lats), sum(lons) / len(lons))
                        _coord_cache[cache_key] = result
                        return result
    except Exception:
        pass
    return None


async def get_soil_properties(parcel_id: str, tenant_id: str = "") -> "SoilProperties":
    """Fetch soil physical properties for a parcel.

    Resolution chain:
    1. Try GET /v1/soil/parcel/{id}/summary (pre-ingested AgriSoilExtended)
    2. Fallback: resolve coords -> GET /v1/soil/point/texture?lat=X&lon=Y
    3. If all fail: return default loam values

    Results cached with 1h TTL.
    """
    from app.schemas import SoilProperties

    cache_key = f"{tenant_id}:{parcel_id}"
    cached = _soil_cache.get(cache_key)
    if cached:
        return SoilProperties(**cached)

    settings = get_settings()
    soil_url = settings.soil_module_url

    soil_data = None

    # Attempt 1: parcel/summary endpoint
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{soil_url}/v1/soil/parcel/{parcel_id}/summary",
                headers={"X-Tenant-ID": tenant_id} if tenant_id else {},
            )
            if resp.status_code == 200:
                data = resp.json()
                horizons = data.get("horizons", {}).get("value", [])
                if horizons:
                    h = horizons[0]
                    soil_data = {
                        "sand_pct": h.get("sand", 40),
                        "clay_pct": h.get("clay", 20),
                        "silt_pct": h.get("silt", 40),
                        "organic_carbon_pct": h.get("organicCarbon", 1.0),
                        "field_capacity": h.get("fieldCapacity", 0.27),
                        "wilting_point": h.get("wiltingPoint", 0.12),
                        "ksat_mm_h": h.get("saturatedHydraulicConductivity", 13.0),
                        "scs_hydrologic_group": h.get("hydrologicGroup", "B"),
                        "usda_texture_class": h.get("usdaTextureClass", "loam"),
                        "source": data.get("dataSource", {}).get("value", "lab_analysis"),
                        "has_data": True,
                    }
    except Exception:
        pass

    # Attempt 2: point/texture fallback with parcel coords
    if soil_data is None:
        coords = await _resolve_parcel_coords(parcel_id, tenant_id)
        if coords:
            lat, lon = coords
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"{soil_url}/v1/soil/point/texture",
                        params={"lat": lat, "lon": lon, "depth": "0-60"},
                        headers={"X-Tenant-ID": tenant_id} if tenant_id else {},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        tex = data.get("texture", {})
                        hyd = data.get("hydraulic", {})
                        soil_data = {
                            "sand_pct": tex.get("sand", 40),
                            "clay_pct": tex.get("clay", 20),
                            "silt_pct": tex.get("silt", 40),
                            "organic_carbon_pct": tex.get("organicCarbon", 1.0),
                            "field_capacity": hyd.get("fieldCapacity", 0.27),
                            "wilting_point": hyd.get("wiltingPoint", 0.12),
                            "ksat_mm_h": hyd.get("saturatedHydraulicConductivity", 13.0),
                            "scs_hydrologic_group": hyd.get("hydrologicGroup", "B"),
                            "usda_texture_class": tex.get("usdaTextureClass", "loam"),
                            "source": data.get("source", {}).get("provider", "soilgrids"),
                            "has_data": True,
                        }
            except Exception:
                pass

    # Default fallback
    if soil_data is None:
        soil_data = dict(_DEFAULT_SOIL_DICT)
        logger.warning("No soil data for parcel %s — using default loam", parcel_id)
    else:
        logger.info(
            "Soil data for parcel %s from %s: %s, FC=%.2f WP=%.2f ksat=%.1f",
            parcel_id, soil_data["source"], soil_data["usda_texture_class"],
            soil_data["field_capacity"], soil_data["wilting_point"], soil_data["ksat_mm_h"],
        )

    _soil_cache[cache_key] = soil_data
    return SoilProperties(**soil_data)


# ── F4: Crop Context from BioOrchestrator ────────────────────────────────────

_crop_context_cache: TTLCache[str, "CropContext"] = TTLCache(maxsize=128, ttl=3600)


async def get_crop_context(
    parcel_id: str,
    tenant_id: str = "",
    gdd: float | None = None,
):
    """Fetch full crop context from BioOrchestrator.

    Calls GET /api/graph/agriculture/crop-context?parcel_id=X.
    Returns None if BioOrchestrator unreachable (circuit breaker).
    Uses TTLCache with 1h TTL.
    """
    from app.schemas import CropContext

    cache_key = f"{tenant_id}:{parcel_id}:{gdd or 0}"
    cached = _crop_context_cache.get(cache_key)
    if cached is not None:
        return cached

    settings = get_settings()
    if not settings.bioorchestrator_url:
        logger.warning("BIOORCHESTRATOR_URL not configured — crop context unavailable")
        return None

    url = f"{settings.bioorchestrator_url}/api/graph/agriculture/crop-context"
    params: dict = {"parcel_id": parcel_id}
    if gdd is not None:
        params["gdd"] = str(gdd)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                ctx = CropContext(**data)
                _crop_context_cache[cache_key] = ctx
                logger.info(
                    "Crop context for parcel %s: species=%s variety=%s match=%s",
                    parcel_id,
                    data.get("crop", {}).get("eppo"),
                    data.get("variety", {}).get("name"),
                    data.get("match_level"),
                )
                return ctx
            elif resp.status_code == 404:
                logger.info("No crop context for parcel %s (404 — no crop assigned)", parcel_id)
                return None
            else:
                logger.warning("BioOrchestrator returned %d for crop-context", resp.status_code)
    except httpx.TimeoutException:
        logger.warning("BioOrchestrator timeout for crop-context")
    except httpx.ConnectError:
        logger.warning("BioOrchestrator unreachable for crop-context")
    except Exception as exc:
        logger.error("Unexpected error from bioorchestrator crop-context: %s", exc)

    return None


# ── Soil Susceptibility (Phase 2 — Compaction Risk) ───────────────────────────

_soil_susceptibility_cache: TTLCache[str, dict] = TTLCache(maxsize=128, ttl=86400)


async def get_soil_susceptibility(parcel_id: str, tenant_id: str) -> dict | None:
    """Fetch compaction susceptibility from the soil module.

    Calls GET /v1/soil/parcel/{id}/compaction-susceptibility on the
    soil module API. Result is cached for 24h (soil data is static).

    Returns:
        {
            "overall_score": float,
            "overall_class": str,
            "worst_horizon_score": float,
            "worst_horizon_class": str,
            "by_horizon": [...],
        }
        or None if soil module is unreachable or parcel has no soil data.
    """
    settings = get_settings()
    soil_url = settings.soil_module_url
    if not soil_url:
        logger.warning("SOIL_MODULE_URL not configured — compaction risk unavailable")
        return None

    cache_key = f"{tenant_id}:{parcel_id}"
    cached = _soil_susceptibility_cache.get(cache_key)
    if cached is not None:
        return cached

    url = f"{soil_url}/v1/soil/parcel/{parcel_id}/compaction-susceptibility"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                headers={"X-Tenant-ID": tenant_id} if tenant_id else {},
            )
            if resp.status_code == 200:
                data = resp.json()
                overall = data.get("overall", {})
                result = {
                    "overall_score": overall.get("score"),
                    "overall_class": overall.get("class"),
                    "worst_horizon_score": overall.get("worstHorizonScore"),
                    "worst_horizon_class": overall.get("worstHorizonClass"),
                    "by_horizon": data.get("byHorizon", []),
                }
                _soil_susceptibility_cache[cache_key] = result
                logger.info(
                    "Soil susceptibility for parcel %s: score=%s class=%s",
                    parcel_id, result["overall_score"], result["overall_class"],
                )
                return result
            elif resp.status_code == 404:
                logger.info("No soil data for parcel %s (404)", parcel_id)
                return None
            else:
                logger.warning("Soil module returned %d for parcel %s", resp.status_code, parcel_id)
    except httpx.TimeoutException:
        logger.warning("Soil module timeout for parcel %s", parcel_id)
    except httpx.ConnectError:
        logger.warning("Soil module unreachable for parcel %s", parcel_id)
    except Exception as exc:
        logger.error("Unexpected error from soil module: %s", exc)

    return None


# ── Multi-year Vigor Anomaly (Phase 3 — Compaction Risk) ─────────────────────

# Growing season months for northern hemisphere (April–October inclusive)
_GROWING_SEASON_MONTHS = {4, 5, 6, 7, 8, 9, 10}


def _extract_season_year(assessed_at_str: str) -> int | None:
    """Extract the growing season year from an ISO-8601 timestamp.

    Timestamps in Apr–Oct belong to the current calendar year's season.
    Timestamps in Jan–Mar belong to the PREVIOUS calendar year's season
    (e.g., March 2025 NDVI is part of the 2024 growing season).

    Returns None if the month is outside the growing season (Nov, Dec).
    """
    try:
        from datetime import datetime as dt
        parsed = dt.fromisoformat(assessed_at_str.replace("Z", "+00:00"))
        month = parsed.month
        year = parsed.year
        if month in _GROWING_SEASON_MONTHS:
            return year
        # Jan–Mar: belongs to previous calendar year's growing season
        if month <= 3:
            return year - 1
        return None
    except (ValueError, TypeError):
        return None


async def get_multiyear_vigor_anomaly(
    parcel_id: str,
    tenant_id: str,
    seasons: int = 3,
) -> dict | None:
    """Analyze multiple growing seasons of vigor data for persistent anomalies.

    Queries Orion-LD for CropHealthAssessment entities linked to this parcel,
    groups by growing season year, computes mean vigor per season, and returns
    the average anomaly vs. the overall multi-year mean.

    Returns None if:
    - Fewer than 2 seasons of data available
    - Orion-LD unreachable
    - Parcel has no assessments

    Returns:
        {
            "avg_anomaly": float,       # -1 to +1, negative = below mean
            "seasons_analyzed": int,    # number of distinct growing seasons
            "seasonal_means": {year: float, ...},
            "overall_mean_vigor": float,
        }
    """
    settings = get_settings()
    orion_url = settings.orion_ld_url

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Query all CropHealthAssessment entities for this parcel
            resp = await client.get(
                f"{orion_url}/ngsi-ld/v1/entities",
                params={
                    "type": "CropHealthAssessment",
                    "q": f'refAgriParcel==\"urn:ngsi-ld:AgriParcel:{parcel_id}\"',
                    "limit": 500,
                    "options": "keyValues",
                },
                headers={
                    "Accept": "application/ld+json",
                    "NGSILD-Tenant": tenant_id,
                } if tenant_id else {"Accept": "application/ld+json"},
            )
            if resp.status_code != 200:
                logger.warning(
                    "Orion-LD returned %d for multi-year vigor query (parcel %s)",
                    resp.status_code, parcel_id,
                )
                return None

            entities = resp.json()
            if not isinstance(entities, list) or len(entities) < 2:
                logger.info(
                    "Insufficient CropHealthAssessment entities for parcel %s: %d",
                    parcel_id, len(entities) if isinstance(entities, list) else 0,
                )
                return None

            # ── Group by growing season year ──
            seasonal_vigors: dict[int, list[float]] = {}
            for e in entities:
                # Handle both flat keyValues and nested NGSI-LD Property format
                raw_at = e.get("assessedAt")
                if isinstance(raw_at, dict):
                    assessed_at = raw_at.get("value")
                else:
                    assessed_at = raw_at

                raw_vigor = e.get("vigorIndex")
                if isinstance(raw_vigor, dict):
                    vigor = raw_vigor.get("value")
                else:
                    vigor = raw_vigor

                if assessed_at is None or vigor is None:
                    continue

                season_year = _extract_season_year(str(assessed_at))
                if season_year is None:
                    continue

                try:
                    vigor_val = float(vigor)
                    if 0.0 <= vigor_val <= 1.0:
                        seasonal_vigors.setdefault(season_year, []).append(vigor_val)
                except (ValueError, TypeError):
                    continue

            # Need at least 2 seasons per Phase 2 engine contract
            if len(seasonal_vigors) < 2:
                logger.info(
                    "Only %d growing season(s) found for parcel %s (need ≥2)",
                    len(seasonal_vigors), parcel_id,
                )
                return None

            # Only keep the most recent N seasons
            sorted_years = sorted(seasonal_vigors.keys(), reverse=True)[:seasons]
            seasonal_vigors = {y: seasonal_vigors[y] for y in sorted_years}

            # ── Compute per-season means ──
            seasonal_means: dict[int, float] = {}
            for year, vigors in seasonal_vigors.items():
                seasonal_means[year] = round(sum(vigors) / len(vigors), 4)

            # ── Overall mean across all seasons ──
            all_vigors = [v for vigors in seasonal_vigors.values() for v in vigors]
            overall_mean = round(sum(all_vigors) / len(all_vigors), 4) if all_vigors else 0.5

            # ── Average anomaly: mean of (season_mean - overall_mean) ──
            anomalies = [seasonal_means[y] - overall_mean for y in sorted_years]
            avg_anomaly = round(sum(anomalies) / len(anomalies), 4) if anomalies else 0.0

            seasons_count = len(seasonal_vigors)

            logger.info(
                "Multi-year vigor for parcel %s: %d seasons, mean=%.3f, anomaly=%.3f",
                parcel_id, seasons_count, overall_mean, avg_anomaly,
            )

            return {
                "avg_anomaly": avg_anomaly,
                "seasons_analyzed": seasons_count,
                "seasonal_means": seasonal_means,
                "overall_mean_vigor": overall_mean,
            }

    except httpx.TimeoutException:
        logger.warning("Orion-LD timeout for multi-year vigor query (parcel %s)", parcel_id)
    except httpx.ConnectError:
        logger.warning("Orion-LD unreachable for multi-year vigor query")
    except Exception as exc:
        logger.error("Unexpected error in multi-year vigor analysis: %s", exc)

    return None


# ── Penetrometer Ground Truth (Phase 4c — Compaction Risk) ──────────────────


async def get_penetrometer_data(
    parcel_id: str,
    tenant_id: str,
) -> dict | None:
    """Check if real penetrometer measurements exist for a parcel.

    Queries Orion-LD for SoilSamplingPoint entities linked to this parcel
    that have penetrationResistance data. If found, the compaction risk
    engine can use this as ground truth instead of modeled susceptibility.

    Returns None if no penetrometer data exists.

    Returns:
        {
            "available": True,
            "point_count": int,
            "mean_mpa": float,
            "max_mpa": float,
            "depth_range": str,
        }
    """
    settings = get_settings()
    orion_url = settings.orion_ld_url

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{orion_url}/ngsi-ld/v1/entities",
                params={
                    "type": "SoilSamplingPoint",
                    "q": f'refAgriParcel==\"urn:ngsi-ld:AgriParcel:{parcel_id}\"',
                    "limit": 50,
                    "options": "keyValues",
                },
                headers={
                    "Accept": "application/ld+json",
                    "NGSILD-Tenant": tenant_id,
                } if tenant_id else {"Accept": "application/ld+json"},
            )
            if resp.status_code != 200:
                return None

            entities = resp.json()
            if not isinstance(entities, list):
                return None

            mpa_values = []
            for e in entities:
                pr = e.get("penetrationResistance")
                if isinstance(pr, dict):
                    pr = pr.get("value")
                if pr is not None:
                    try:
                        val = float(pr)
                        if val > 0:
                            mpa_values.append(val)
                    except (ValueError, TypeError):
                        pass

            if len(mpa_values) < 1:
                return None

            depths = set()
            for e in entities:
                df = e.get("depthFrom", {}).get("value") if isinstance(e.get("depthFrom"), dict) else e.get("depthFrom")
                dt = e.get("depthTo", {}).get("value") if isinstance(e.get("depthTo"), dict) else e.get("depthTo")
                if df is not None and dt is not None:
                    depths.add(f"{df}-{dt}")

            return {
                "available": True,
                "point_count": len(mpa_values),
                "mean_mpa": round(sum(mpa_values) / len(mpa_values), 2),
                "max_mpa": round(max(mpa_values), 2),
                "depth_range": ", ".join(sorted(depths)) if depths else "unknown",
            }

    except Exception:
        pass

    return None
