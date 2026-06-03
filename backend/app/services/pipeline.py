"""
Pipeline Orchestrator — Webhook → Normalise → Enrich → Compute → Publish.

This is the core orchestration layer that wires together:
1. Redis temporal state
2. Context clients (weather, phenology)
3. Biophysical engines (CWSI, MDS, Water Balance)
4. FIWARE publisher

Architecture note: This module COMPLEMENTS the risk-worker's
water_stress_model.py. The risk-worker uses batch meteorological data
(precip-eto balance); this module adds real-time canopy-level sensing
(IR temperature → CWSI, dendrómetro → MDS) for precision agriculture.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.engines.mds_model import calculate_mds_from_readings
from app.engines.water_balance import dynamic_water_balance
from app.engines.water_stress import cwsi_with_weather
from app.schemas import (
    CropHealthAssessment,
    MetricType,
    RecommendedAction,
    Severity,
    ThermalStressResult,
    VigorResult as VigorResultSchema,
)
from app.services.context_client import get_phenology_params, get_weather_snapshot
from app.services.fiware_publisher import publish_assessment
from app.services.redis_state import RedisState

logger = logging.getLogger(__name__)


def _determine_overall_severity(assessment: CropHealthAssessment) -> Severity:
    """Determine overall severity from individual engine results.

    Strategy: worst-case (maximum severity) across all available signals.
    """
    severities: list[Severity] = []

    if assessment.cwsi:
        if assessment.cwsi.cwsi >= 0.7:
            severities.append(Severity.CRITICAL)
        elif assessment.cwsi.cwsi >= 0.5:
            severities.append(Severity.HIGH)
        elif assessment.cwsi.cwsi >= 0.3:
            severities.append(Severity.MEDIUM)
        else:
            severities.append(Severity.LOW)

    if assessment.mds:
        severities.append(assessment.mds.severity)

    if assessment.water_balance and assessment.water_balance.deficit:
        if assessment.water_balance.balance_mm < -15:
            severities.append(Severity.CRITICAL)
        elif assessment.water_balance.balance_mm < -5:
            severities.append(Severity.HIGH)
        else:
            severities.append(Severity.MEDIUM)

    if not severities:
        return Severity.LOW

    # Worst-case ordering
    order = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}
    return max(severities, key=lambda s: order[s])


def _determine_action(severity: Severity) -> RecommendedAction:
    """Map overall severity to recommended action."""
    return {
        Severity.LOW: RecommendedAction.NO_ACTION,
        Severity.MEDIUM: RecommendedAction.MONITOR,
        Severity.HIGH: RecommendedAction.IRRIGATE_SCHEDULED,
        Severity.CRITICAL: RecommendedAction.IRRIGATE_IMMEDIATE,
    }[severity]


async def trigger(
    entity_id: str,
    metric_type: str,
    redis_state: RedisState,
    parcel_id: str | None = None,
    tenant_id: str = "",
) -> CropHealthAssessment | None:
    """Execute the full inference pipeline.

    Called asynchronously when a FIWARE webhook delivers new sensor data.

    Flow:
    1. Identify the parcel associated with the sensor
    2. Fetch phenology params (cached, with fallback defaults)
    3. Fetch weather snapshot from TimescaleDB
    4. Read sensor data from Redis sliding window
    5. Execute relevant engine(s) based on metric_type
    6. Fuse results into CropHealthAssessment
    7. Publish to Orion-LD

    Args:
        entity_id: NGSI-LD device entity ID.
        metric_type: The metric that triggered this pipeline.
        redis_state: Redis client for sliding window access.
        parcel_id: If already known from webhook; else resolved from entity.
        tenant_id: Tenant ID for weather DB query.

    Returns:
        CropHealthAssessment if computed, None on error.
    """
    effective_parcel = parcel_id or _extract_parcel_from_entity(entity_id)
    if not effective_parcel:
        logger.warning("Cannot resolve parcel for entity %s — skipping", entity_id)
        return None

    logger.info(
        "Pipeline triggered: entity=%s metric=%s parcel=%s",
        entity_id,
        metric_type,
        effective_parcel,
    )

    # ── 1. Fetch context ─────────────────────────────────────────────────
    # Resolve crop/variety from BioOrchestrator crop-context
    from app.services.context_client import get_crop_context as fetch_crop_context

    species = "generic"
    variety_name = None
    management = None
    crop_context = None

    try:
        crop_context = await fetch_crop_context(
            parcel_id=effective_parcel,
            tenant_id=tenant_id,
        )
        if crop_context:
            if crop_context.crop and crop_context.crop.eppo != "unknown":
                species = crop_context.crop.eppo
            elif crop_context.crop and crop_context.crop.name:
                species = crop_context.crop.name
            variety_name = crop_context.variety.name if crop_context.variety else None
            management = crop_context.management
            if crop_context.season and crop_context.season.gdd_accumulated:
                gdd = crop_context.season.gdd_accumulated
    except Exception:
        pass

    # GDD fallback
    gdd = None
    try:
        from datetime import date
        season_start = date(date.today().year, 3, 1).isoformat()  # March 1st default
        gdd_data = await _fetch_gdd(tenant_id, season_start, 10.0)
        if gdd_data and gdd_data.get("gdd_total"):
            gdd = float(gdd_data["gdd_total"])
    except Exception:
        pass

    phenology = await get_phenology_params(species=species, gdd=gdd)
    weather = await get_weather_snapshot(
        latitude=0.0,  # TODO: resolve from parcel geometry
        longitude=0.0,
        tenant_id=tenant_id,
    )

    now = datetime.now(timezone.utc)
    assessment = CropHealthAssessment(
        parcel_id=effective_parcel,
        assessed_at=now,
        phenology_source=crop_context.phenology_source if crop_context else "default",
        crop_species=species if species != "generic" else None,
        crop_name=crop_context.crop.name if crop_context and crop_context.crop else None,
        variety_name=variety_name,
        phenology_stage=phenology.stage if phenology else None,
        gdd_accumulated=gdd,
        kc=phenology.kc if phenology else None,
        management=management,
    )

    # ── 2. Execute engines ───────────────────────────────────────────────

    # CWSI (triggered by leaf temperature sensor)
    if metric_type == MetricType.LEAF_TEMPERATURE.value and weather:
        readings = await redis_state.get_window(entity_id, "leafTemperature", hours=1)
        if readings:
            latest_tc = readings[-1].value
            assessment.cwsi = cwsi_with_weather(
                temp_canopy=latest_tc,
                temp_air=weather.temp_air,
                humidity_pct=weather.humidity_pct,
                d1=phenology.d1,
                d2=phenology.d2,
            )

    # MDS (triggered by trunk diameter dendrómetro)
    if metric_type == MetricType.TRUNK_DIAMETER.value:
        readings = await redis_state.get_window(entity_id, "trunkDiameter", hours=24)
        assessment.mds = calculate_mds_from_readings(readings, mds_ref=phenology.mds_ref)

    # Water balance (triggered by soil moisture or opportunistically)
    if weather:
        assessment.water_balance = dynamic_water_balance(
            precipitation_mm=weather.precip_mm,
            eto_mm=weather.eto_mm,
            kc=phenology.kc,
        )

    # Thermal stress (triggered by leaf temperature or opportunistically with weather)
    if weather:
        try:
            from app.engines.thermal_stress import evaluate_thermal_stress
            leaf_temp = None
            if metric_type == MetricType.LEAF_TEMPERATURE.value:
                readings = await redis_state.get_window(entity_id, "leafTemperature", hours=1)
                if readings:
                    leaf_temp = readings[-1].value
            tr = evaluate_thermal_stress(
                leaf_temp=leaf_temp,
                air_temp=weather.temp_air,
                fidelity="onsite_uncalibrated" if leaf_temp is not None else "regional_proxy",
            )
            assessment.thermal = ThermalStressResult(
                heat_stress_hours=tr.heat_stress_hours,
                frost_hours=tr.frost_hours,
                condition=tr.condition,
                severity=tr.severity,
                data_fidelity=tr.data_fidelity,
            )
        except Exception:
            pass

    # Vigor (opportunistic — fetches latest vegetation index for the parcel)
    try:
        from app.engines.vigor import evaluate_vigor
        ndvi_val = await _fetch_parcel_ndvi(effective_parcel, tenant_id)
        if ndvi_val is not None or assessment.cwsi is not None:
            cwsi_val = assessment.cwsi.cwsi if assessment.cwsi else None
            stage_name = phenology.stage if phenology else "vegetative"
            vr = evaluate_vigor(
                ndvi=ndvi_val,
                cwsi=cwsi_val,
                stage=stage_name,
                fidelity="onsite_uncalibrated" if ndvi_val is not None else "modeled_opendata",
            )
            assessment.vigor = VigorResultSchema(
                vigor_index=vr.vigor_index,
                growth_anomaly=vr.growth_anomaly,
                index_used=vr.index_used,
                condition=vr.condition,
                data_fidelity=vr.data_fidelity,
            )
    except Exception:
        pass

    # ── 2.4 Soil sensor readings (pass-through, no engine) ────────────
    soil_ph_val = None
    soil_ec_val = None
    soil_moisture_val = None
    soil_temp_val = None

    if metric_type in (
        MetricType.SOIL_PH.value,
        MetricType.SOIL_EC.value,
        MetricType.SOIL_MOISTURE.value,
        MetricType.SOIL_TEMPERATURE.value,
    ):
        readings = await redis_state.get_window(entity_id, metric_type, hours=1)
        if readings:
            latest = readings[-1].value
            if metric_type == MetricType.SOIL_PH.value:
                soil_ph_val = latest
            elif metric_type == MetricType.SOIL_EC.value:
                soil_ec_val = latest
            elif metric_type == MetricType.SOIL_MOISTURE.value:
                soil_moisture_val = latest
            elif metric_type == MetricType.SOIL_TEMPERATURE.value:
                soil_temp_val = latest

    # ── 2.5 Compound engines (after individual engines have results) ────
    stage_name = "vegetative"  # safe default for Redis event publishing
    try:
        from app.engines.composite import evaluate_composite_stress
        thermal_sev = assessment.thermal.severity if assessment.thermal else None
        vigor_idx = assessment.vigor.vigor_index if assessment.vigor else None
        mds_ratio_val = assessment.mds.ratio if assessment.mds else None
        wb_mm = assessment.water_balance.balance_mm if assessment.water_balance else None
        cwsi_val = assessment.cwsi.cwsi if assessment.cwsi else None
        stage_name = phenology.stage if phenology else "vegetative"
        # Build Ky map from crop-context if available
        ky_by_stage = None
        if crop_context and crop_context.phenology and crop_context.phenology.stage and crop_context.phenology.ky is not None:
            ky_by_stage = {crop_context.phenology.stage: crop_context.phenology.ky}
        assessment.composite_stress = evaluate_composite_stress(
            cwsi=cwsi_val, mds_ratio=mds_ratio_val, water_balance_mm=wb_mm,
            thermal_severity=thermal_sev, vigor_index=vigor_idx,
            stage=stage_name,
            ky_override=ky_by_stage,
        )
    except Exception:
        pass

    try:
        from app.engines.yield_gap import evaluate_yield_gap
        _cwsi = assessment.cwsi.cwsi if assessment.cwsi else None
        if _cwsi is not None:
            stage_name = phenology.stage if phenology else "vegetative"
            assessment.yield_gap = evaluate_yield_gap(
                cwsi_by_stage={stage_name: _cwsi},
                ky_by_stage={stage_name: phenology.ky if phenology and hasattr(phenology, 'ky') else 0.45},
            )
    except Exception:
        pass

    try:
        from app.engines.phenology_progress import evaluate_phenology_progress
        if gdd is not None and phenology:
            stage_name = phenology.stage if phenology else "vegetative"
            thresholds: dict[str, tuple[float, float]] = {}
            if phenology.stage_gdd_min is not None and phenology.stage_gdd_max is not None:
                thresholds[stage_name] = (phenology.stage_gdd_min, phenology.stage_gdd_max)
            assessment.phenology_progress = evaluate_phenology_progress(
                gdd_accumulated=gdd, current_stage=stage_name, stage_gdd_thresholds=thresholds,
            )
    except Exception:
        pass

    # WUE (after composite stress and yield gap, needs NDVI integral + irrigation data)
    try:
        from app.engines.wue import evaluate_wue
        ndvi_val = await _fetch_parcel_ndvi(effective_parcel, tenant_id)
        irrigation_mm = None
        irrigation_source = "none"
        try:
            irr_readings = await redis_state.get_window(entity_id, "irrigationVolume", hours=24)
            if irr_readings:
                irrigation_mm = sum(r.value for r in irr_readings)
                irrigation_source = "measured_flow"
        except Exception:
            pass
        if irrigation_source == "none":
            try:
                declared = await redis_state.get_latest(entity_id, "declaredIrrigation")
                if declared and declared.value:
                    irrigation_mm = declared.value
                    irrigation_source = "declared_volume"
            except Exception:
                pass
        assessment.wue = evaluate_wue(
            ndvi_integrated=ndvi_val,
            irrigation_applied_mm=irrigation_mm,
            irrigation_source=irrigation_source,
            previous_wue=None,
            fidelity="onsite_uncalibrated" if irrigation_source == "measured_flow" else "regional_proxy",
        )
    except Exception:
        pass

    assessment.data_fidelity = _resolve_data_fidelity(assessment)

    # Soil sensor pass-through values
    assessment.soil_ph = soil_ph_val
    assessment.soil_ec = soil_ec_val
    assessment.soil_moisture_pct = soil_moisture_val
    assessment.soil_temperature_c = soil_temp_val

    # ── 3. Fuse and classify ─────────────────────────────────────────────
    assessment.overall_severity = _determine_overall_severity(assessment)
    assessment.recommended_action = _determine_action(assessment.overall_severity)

    # ── 4. Publish ───────────────────────────────────────────────────────
    published = await publish_assessment(assessment, tenant_id)
    if published:
        logger.info(
            "Assessment published: parcel=%s severity=%s action=%s",
            effective_parcel,
            assessment.overall_severity.value,
            assessment.recommended_action.value,
        )
    else:
        logger.warning("Failed to publish assessment for parcel=%s", effective_parcel)

    # ── 5. Publish to platform event bus ─────────────────────────────────
    try:
        import json as _json
        event = {
            "event_type": "crop.assessment.completed",
            "tenant_id": tenant_id,
            "parcel_id": effective_parcel,
            "stage": stage_name,
            "cwsi": assessment.cwsi.cwsi if assessment.cwsi else None,
            "mds_severity": assessment.mds.severity.value if assessment.mds else None,
            "overall_severity": assessment.overall_severity.value,
            "recommended_action": assessment.recommended_action.value,
            "phenology_source": assessment.phenology_source,
            "timestamp": now.isoformat(),
        }
        await _publish_redis_event("crop:events", event)

        if assessment.overall_severity.value in ("HIGH", "CRITICAL"):
            breach = {
                "event_type": "crop.stress.breach",
                "tenant_id": tenant_id,
                "parcel_id": effective_parcel,
                "stage": stage_name,
                "overall_severity": assessment.overall_severity.value,
                "recommended_action": assessment.recommended_action.value,
                "timestamp": now.isoformat(),
            }
            await _publish_redis_event("crop:events", breach)
    except Exception:
        pass  # Event bus is best-effort, never block the pipeline

    return assessment


async def _publish_redis_event(stream: str, event: dict) -> None:
    """Publish an event to Redis Streams (best-effort)."""
    try:
        import redis.asyncio as aioredis
        r = aioredis.Redis.from_url("redis://redis-service:6379/0")
        payload = __import__("json").dumps(event)
        await r.xadd(stream, {"payload": payload}, maxlen=1000)
        await r.aclose()
    except Exception:
        pass


async def _fetch_gdd(tenant_id: str, season_start: str, base_temp: float = 10.0) -> dict | None:
    """Fetch accumulated GDD from the weather API."""
    try:
        settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
        if not settings.weather_api_url:
            return None
        async with __import__("httpx").AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.weather_api_url}/api/weather/gdd",
                params={"season_start": season_start, "base_temp": base_temp},
                headers={"X-Tenant-ID": tenant_id},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


async def _fetch_parcel_ndvi(parcel_id: str, tenant_id: str) -> float | None:
    """Fetch latest NDVI value for a parcel from Orion-LD VegetationIndex entities."""
    try:
        settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
        orion_url = settings.orion_ld_url
        async with __import__("httpx").AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{orion_url}/ngsi-ld/v1/entities",
                params={
                    "type": "VegetationIndex",
                    "q": f'refAgriParcel==\"urn:ngsi-ld:AgriParcel:{parcel_id}\"',
                    "limit": 1,
                    "options": "keyValues",
                },
                headers={
                    "Accept": "application/ld+json",
                    "NGSILD-Tenant": tenant_id,
                    "Fiware-Service": tenant_id,
                    "Fiware-ServicePath": "/",
                } if tenant_id else {"Accept": "application/ld+json"},
            )
            if resp.status_code == 200:
                entities = resp.json()
                if entities and isinstance(entities, list):
                    e = entities[0]
                    ndvi = e.get("ndviValue") or e.get("value")
                    if ndvi is not None:
                        return float(ndvi)
    except Exception:
        pass
    return None


def _resolve_data_fidelity(assessment: CropHealthAssessment) -> str:
    """Determine the minimum data fidelity from available inputs."""
    levels = []
    if assessment.cwsi:
        levels.append("onsite_uncalibrated")  # CWSI requires IR sensor
    if assessment.mds:
        levels.append("onsite_uncalibrated")  # MDS requires dendrometer
    if assessment.water_balance:
        levels.append("regional_proxy")  # weather API
    if assessment.thermal:
        levels.append(assessment.thermal.data_fidelity)
    if assessment.vigor:
        levels.append(assessment.vigor.data_fidelity)

    priority = ["onsite_calibrated", "onsite_uncalibrated", "local_proxy",
                "regional_proxy", "modeled_opendata"]
    if not levels:
        return "modeled_opendata"
    # Return the lowest fidelity (highest index in priority list)
    for p in reversed(priority):
        if p in levels:
            return p
    return "mixed"


def _extract_parcel_from_entity(entity_id: str) -> str | None:
    """Extract parcel ID from device entity ID.

    Convention: device entities follow the pattern
    urn:ngsi-ld:DeviceMeasurement:{parcel}-{sensor}
    or carry a refAgriParcel relationship.

    For now, use a simple heuristic; the webhook handler can
    pass parcel_id directly if resolved upstream.
    """
    # Simple heuristic: extract the first segment after DeviceMeasurement:
    parts = entity_id.split(":")
    if len(parts) >= 4:
        # urn:ngsi-ld:DeviceMeasurement:Parcela-4-sensor-1 → Parcela-4
        sensor_part = parts[3]
        # Take everything before the last dash-delimited segment
        segments = sensor_part.rsplit("-", 1)
        if len(segments) >= 1:
            return segments[0]
    return None
