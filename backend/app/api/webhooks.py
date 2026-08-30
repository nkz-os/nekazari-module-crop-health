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

from fastapi import HTTPException

from app.config import get_settings
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


def _validate_webhook_secret(request: Request) -> None:
    """Validate X-Orion-Webhook-Secret if configured (defense-in-depth)."""
    secret = get_settings().orion_webhook_secret
    if not secret:
        return
    provided = request.headers.get("X-Orion-Webhook-Secret", "")
    if provided != secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")


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
                "id": "urn:ngsi-ld:DeviceMeasurement:{tenant}:{device}:leafTemperature",
                "type": "DeviceMeasurement",
                "refDevice": {"type": "Relationship",
                              "object": "urn:ngsi-ld:Device:{tenant}:{device}"},
                "controlledProperty": {"type": "Property", "value": "leafTemperature"},
                "numValue": {"type": "Property", "value": 32.5, "unitCode": "CEL"},
                "dateObserved": {"type": "Property", "value": "2026-08-29T09:00:00Z"}
            }
        ]
    }
    """
    _validate_webhook_secret(request)
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
        device_id, metric_name, value, observed_ts = _read_measurement(entity)
        if device_id is None:
            logger.debug(
                "Skipping %s: missing refDevice, controlledProperty or reading",
                entity.get("id", "<no id>"),
            )
            continue

        metric_type = _TRACKED_ATTRIBUTES.get(metric_name)
        if metric_type is None:
            continue

        # Redis sliding window, keyed by device — stable across readings
        await redis_state.store_reading(
            device_id=device_id,
            metric=metric_name,
            timestamp=observed_ts if observed_ts is not None else now_ts,
            value=value,
        )

        # The parcel is not on the measurement: it hangs off the device's
        # controlledAsset, one hop away, so the pipeline resolves it rather
        # than the request path.
        background_tasks.add_task(
            pipeline.trigger,
            entity_id=device_id,
            metric_type=metric_type.value,
            redis_state=redis_state,
            parcel_id=None,
            tenant_id=tenant_id,
        )

        logger.info(
            "Webhook: %s.%s=%.2f -> pipeline queued", device_id, metric_name, value
        )

    return Response(status_code=204)


def _read_measurement(
    entity: dict,
) -> tuple[str | None, str | None, float | None, float | None]:
    """Pull (device_id, metric_name, value, observed_ts) out of a `DeviceMeasurement`.

    `DeviceMeasurement` inverts the shape used by entities that carry their
    readings as attributes: the measured property's name is the VALUE of
    ``controlledProperty`` rather than an attribute key, the reading sits in
    ``numValue`` or ``textValue`` (never both), the device is the ``refDevice``
    relationship — NOT the last segment of this entity's own id, which is the
    property name — and the instant is ``dateObserved``, a plain Property, not
    per-attribute ``observedAt`` metadata.

    Returns ``(None, None, None, None)`` when the device or the reading is
    missing, so the caller skips the entity rather than persisting a guessed
    device id.
    """
    ref_device = entity.get("refDevice")
    if not isinstance(ref_device, dict):
        return None, None, None, None
    device_id = ref_device.get("object")
    if not isinstance(device_id, str) or not device_id:
        return None, None, None, None

    controlled_property = entity.get("controlledProperty")
    if not isinstance(controlled_property, dict):
        return None, None, None, None
    metric_name = controlled_property.get("value")
    if not isinstance(metric_name, str) or not metric_name:
        return None, None, None, None

    value = None
    for value_key in ("numValue", "textValue"):
        value_attr = entity.get(value_key)
        if isinstance(value_attr, dict) and value_attr.get("value") is not None:
            value = value_attr["value"]
            break
    if value is None:
        return None, None, None, None
    try:
        value = float(value)
    except (TypeError, ValueError):
        logger.warning(
            "Non-numeric %s on %s: %s", metric_name, entity.get("id", "<no id>"), value
        )
        return None, None, None, None

    return device_id, metric_name, value, _observed_timestamp(entity)


def _observed_timestamp(entity: dict) -> float | None:
    """Read ``dateObserved`` as a POSIX timestamp; None when absent or unparseable."""
    date_observed = entity.get("dateObserved")
    if not isinstance(date_observed, dict):
        return None
    raw = date_observed.get("value")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()
