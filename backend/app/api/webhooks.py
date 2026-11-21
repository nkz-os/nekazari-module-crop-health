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
import os
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from nkz_platform_sdk.device_measurement import read_device_measurement
from nkz_platform_sdk.notify_auth import accept_master_from_env, verify_notification

from app.schemas import MetricType
from app.services import pipeline
from app.services.observation_medium import DeviceMediumGate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

# Attributes we process — anything else is ignored
_TRACKED_ATTRIBUTES = {
    "leafTemperature": MetricType.LEAF_TEMPERATURE,
    "trunkDiameter": MetricType.TRUNK_DIAMETER,
    "stemDiameter": MetricType.TRUNK_DIAMETER,
    "soilMoisture": MetricType.SOIL_MOISTURE,
    "airTemperature": MetricType.AIR_TEMPERATURE,
    "relativeHumidity": MetricType.RELATIVE_HUMIDITY,
    "photosyntheticPhotonFluxDensity": MetricType.PAR,
    "solarRadiation": MetricType.SOLAR_RADIATION,
}


def _reject_unauthenticated_notify(headers) -> HTTPException | None:
    """401 unless the notification authenticates (flag-gated).

    Two-phase rollout: NOTIFY_REQUIRE_INTERNAL_SECRET stays off until subscription
    creators have converged to carry receiverInfo, then flips on with no code deploy.
    Accepts the token bound to this tenant and host (nkz_platform_sdk.notify_auth)
    and, until NKZ_NOTIFY_ACCEPT_MASTER is false, the master secret itself.
    """
    require = os.getenv("NOTIFY_REQUIRE_INTERNAL_SECRET", "").lower() in (
        "1", "true", "yes", "on"
    )
    if not require:
        return None
    if not verify_notification(
        headers,
        secret=os.getenv("INTERNAL_SERVICE_SECRET", ""),
        accept_master=accept_master_from_env(),
    ):
        return HTTPException(status_code=401, detail="missing or invalid notification credentials")
    return None

async def _fetch_device(tenant_id: str, device_id: str) -> dict | None:
    return await pipeline._read_entity(device_id, tenant_id, "device")


# Devices are looked up in the background task, with a short in-process cache.
_medium_gate = DeviceMediumGate(_fetch_device, ttl_s=300.0)

_PIPELINE_METRICS = frozenset(
    {MetricType.LEAF_TEMPERATURE, MetricType.TRUNK_DIAMETER, MetricType.SOIL_MOISTURE}
)


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
    reject = _reject_unauthenticated_notify(request.headers)
    if reject:
        raise reject
    try:
        body = await request.json()
    except Exception as exc:
        logger.warning("Invalid JSON in webhook: %s", exc)
        return Response(status_code=400)

    data = body.get("data", [])
    if not data:
        logger.debug("Empty data in webhook notification")
        return Response(status_code=204)

    # Orion-LD sends NGSILD-Tenant; Fiware-Service is the NGSIv2 name.
    tenant_id = (
        request.headers.get("NGSILD-Tenant") or request.headers.get("Fiware-Service") or ""
    ).strip().lower()
    from app.main import get_redis_state
    redis_state = get_redis_state()
    now_ts = datetime.now(timezone.utc).timestamp()

    for entity in data:
        device_id, metric_name, value, observed_ts, unit_code = _read_measurement(entity)
        if device_id is None:
            logger.debug(
                "Skipping %s: missing refDevice, channel or reading",
                entity.get("id", "<no id>"),
            )
            continue

        metric_type = _TRACKED_ATTRIBUTES.get(metric_name)
        if metric_type is None:
            continue

        background_tasks.add_task(
            _ingest_reading,
            device_id=device_id,
            metric_name=metric_name,
            metric_type=metric_type,
            value=value,
            ts=observed_ts if observed_ts is not None else now_ts,
            unit_code=unit_code,
            tenant_id=tenant_id,
            redis_state=redis_state,
        )

    return Response(status_code=204)


async def _ingest_reading(
    *,
    device_id: str,
    metric_name: str,
    metric_type: MetricType,
    value: float,
    ts: float,
    unit_code: str | None,
    tenant_id: str,
    redis_state,
) -> None:
    """Store one reading and queue its pipeline run, if the sensor measures the right medium.

    Runs in the background so the webhook still answers 204 at once. A reading whose
    medium does not match, or whose Device cannot be read, is dropped.
    """
    if not await _medium_gate.allows(tenant_id, device_id, metric_name):
        return

    # Redis sliding window, keyed by device — stable across readings
    await redis_state.store_reading(
        device_id=device_id, metric=metric_type.value, timestamp=ts, value=value,
    )

    # Before trigger: the engine sees the recorded parcel reading.
    await pipeline.record_parcel_reading(
        device_id=device_id,
        metric=metric_type.value,
        ts=ts,
        value=value,
        unit_code=unit_code,
        tenant_id=tenant_id,
        redis_state=redis_state,
    )

    if metric_type not in _PIPELINE_METRICS:
        return

    # The parcel is not on the measurement: it hangs off the device's
    # controlledAsset, one hop away, so the pipeline resolves it rather
    # than the request path.
    await pipeline.trigger(
        entity_id=device_id,
        metric_type=metric_type.value,
        redis_state=redis_state,
        parcel_id=None,
        tenant_id=tenant_id,
    )
    logger.info("Webhook: %s.%s=%.2f -> pipeline run", device_id, metric_name, value)


def _read_measurement(
    entity: dict,
) -> tuple[str | None, str | None, float | None, float | None, str | None]:
    """Pull (device_id, metric_name, value, observed_ts, unit_code) out of a `DeviceMeasurement`.

    `metric_name` is the reading's CHANNEL (``airTemperature``, ``airTemperatureMin``), read
    with ``nkz_platform_sdk.read_device_measurement`` so both stored shapes give the same
    name: the legacy one (the channel in ``controlledProperty``) and the Smart Data Models
    one (the channel in ``name``, the catalogue property in ``controlledProperty``). The
    reading sits in ``numValue`` or ``textValue``, the device is the ``refDevice``
    relationship — NOT the last segment of this entity's own id — and the instant is
    ``dateObserved``, a plain Property, not per-attribute ``observedAt`` metadata.

    ``unit_code`` is the ``unitCode`` of the ``numValue`` attribute (None when
    absent or the reading came from ``textValue``).

    Returns all-``None`` when the device, the channel or the reading is
    missing, so the caller skips the entity rather than persisting a guessed
    device id.
    """
    reading = read_device_measurement(entity)
    device_id = reading.device_id
    metric_name = reading.channel
    if device_id is None or metric_name is None:
        return None, None, None, None, None
    value = reading.value
    unit_code = reading.unit_code
    if value is None:
        return None, None, None, None, None
    try:
        value = float(value)
    except (TypeError, ValueError):
        logger.warning(
            "Non-numeric %s on %s: %s", metric_name, entity.get("id", "<no id>"), value
        )
        return None, None, None, None, None

    return device_id, metric_name, value, _observed_timestamp(entity), unit_code


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
