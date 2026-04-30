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
    phenology = await get_phenology_params()
    weather = await get_weather_snapshot(
        latitude=0.0,  # TODO: resolve from parcel geometry
        longitude=0.0,
        tenant_id=tenant_id,
    )

    now = datetime.now(timezone.utc)
    assessment = CropHealthAssessment(
        parcel_id=effective_parcel,
        assessed_at=now,
        phenology_source="bioorchestrator" if not phenology.is_default else "default",
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

    # ── 3. Fuse and classify ─────────────────────────────────────────────
    assessment.overall_severity = _determine_overall_severity(assessment)
    assessment.recommended_action = _determine_action(assessment.overall_severity)

    # ── 4. Publish ───────────────────────────────────────────────────────
    published = await publish_assessment(assessment)
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
