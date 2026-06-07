"""
Webhook Handler — Receives FIWARE Orion-LD notifications.

Endpoint: POST /webhooks/fiware-sensors

Processes DeviceMeasurement notifications for:
- leafTemperature (IR sensor → CWSI pipeline)
- trunkDiameter (dendrómetro → MDS pipeline)
- soilMoisture (TDR probe → water balance pipeline)

Processing is async: the webhook returns 204 immediately and
triggers the inference pipeline in a background task.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.schemas import MetricType
from app.services import pipeline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

# Attributes we process — anything else is ignored
_TRACKED_ATTRIBUTES = {
    "leafTemperature": MetricType.LEAF_TEMPERATURE,
    "trunkDiameter": MetricType.TRUNK_DIAMETER,
    "soilMoisture": MetricType.SOIL_MOISTURE,
}


@router.post("/webhooks/fiware-sensors", status_code=204)
async def receive_sensor_data(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """Receive FIWARE Orion-LD subscription notifications.

    Expected payload structure (NGSI-LD notification):
    {
        "subscriptionId": "...",
        "data": [
            {
                "id": "urn:ngsi-ld:DeviceMeasurement:...",
                "type": "DeviceMeasurement",
                "leafTemperature": {"type": "Property", "value": 32.5},
                ...
            }
        ]
    }
    """
    try:
        body = await request.json()
    except Exception as exc:
        logger.warning("Invalid JSON in webhook: %s", exc)
        return Response(status_code=400)

    data = body.get("data", [])
    if not data:
        logger.debug("Empty data in webhook notification")
        return Response(status_code=204)

    tenant_id = request.headers.get("Fiware-Service", "")
    from app.main import get_redis_state
    redis_state = get_redis_state()
    now_ts = datetime.now(timezone.utc).timestamp()

    for entity in data:
        entity_id = entity.get("id", "")
        if not entity_id:
            continue

        # Extract parcel relationship if present
        parcel_ref = entity.get("hasAgriParcel", {})
        parcel_id = None
        if isinstance(parcel_ref, dict):
            obj = parcel_ref.get("object", "")
            if obj:
                # urn:ngsi-ld:AgriParcel:Parcela-4 → Parcela-4
                parts = obj.split(":")
                parcel_id = parts[-1] if parts else None

        # Process each tracked attribute
        for attr_name, metric_type in _TRACKED_ATTRIBUTES.items():
            attr_data = entity.get(attr_name)
            if attr_data is None:
                continue

            value = attr_data.get("value") if isinstance(attr_data, dict) else attr_data
            if value is None:
                continue

            try:
                value = float(value)
            except (TypeError, ValueError):
                logger.warning(
                    "Non-numeric value for %s on %s: %s", attr_name, entity_id, value
                )
                continue

            # Store in Redis sliding window
            await redis_state.store_reading(
                device_id=entity_id,
                metric=attr_name,
                timestamp=now_ts,
                value=value,
            )

            # Trigger inference pipeline in background
            background_tasks.add_task(
                pipeline.trigger,
                entity_id=entity_id,
                metric_type=metric_type.value,
                redis_state=redis_state,
                parcel_id=parcel_id,
                tenant_id=tenant_id,
            )

            logger.info(
                "Webhook: %s.%s=%.2f → pipeline queued (parcel=%s)",
                entity_id,
                attr_name,
                value,
                parcel_id,
            )

    return Response(status_code=204)
