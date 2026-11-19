"""Which sensor readings may feed crop-health: only those measuring the right medium.

A Device may declare ``observationContext`` (``{"medium": ...}``) and per-attribute
``channelOverrides``. The effective medium of an attribute is its override's medium if
present, else the Device's. A Device with no declared medium has none: never assumed.

A reading is used only when its effective medium equals the one its metric needs
(open-air meteo, soil, plant). Anything else is ignored, never an error.
"""
from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

from app.services.parcel_link import UNDER_PANEL, owner_from_link

logger = logging.getLogger(__name__)

REQUIRED_MEDIUM: dict[str, str] = {
    "airTemperature": "ambientAir",
    "relativeHumidity": "ambientAir",
    "photosyntheticPhotonFluxDensity": "ambientAir",
    "solarRadiation": "ambientAir",
    "soilMoisture": "soil",
    "leafTemperature": "plant",
    "trunkDiameter": "plant",
    "stemDiameter": "plant",
}
_UNDER_STRUCTURE = "ambientAirUnderStructure"
# Metrics the under-panel context of a solar-park device legitimately reads in the air
# below the structure (shade / under-panel stress engines keep their own context).
_AIR_METRICS = frozenset(
    {"airTemperature", "relativeHumidity", "photosyntheticPhotonFluxDensity", "solarRadiation"}
)
_CONTEXT_KEYS = ("observationContext", "https://nkz-os.org/ns/observationContext")
_OVERRIDE_KEYS = ("channelOverrides", "https://nkz-os.org/ns/channelOverrides")


def _property_value(entity: dict, keys) -> object:
    """Value of the first key present, normalized or keyValues form."""
    for key in keys:
        if key in entity:
            raw = entity[key]
            if isinstance(raw, dict) and raw.get("type") == "Property" and "value" in raw:
                return raw["value"]
            return raw
    return None


def effective_medium(device: dict, attribute: str) -> str | None:
    """Medium of one attribute of a Device entity; None when none is declared."""
    channels = _property_value(device, _OVERRIDE_KEYS)
    if isinstance(channels, dict):
        override = channels.get(attribute)
        ctx = override.get("observationContext") if isinstance(override, dict) else None
        if isinstance(ctx, dict) and isinstance(ctx.get("medium"), str):
            return ctx["medium"]
    ctx = _property_value(device, _CONTEXT_KEYS)
    if isinstance(ctx, dict) and isinstance(ctx.get("medium"), str):
        return ctx["medium"]
    return None


def _park_owned(device: dict) -> bool:
    owner = owner_from_link(device.get("controlledAsset"))
    return owner is not None and owner[0] == UNDER_PANEL


def reading_allowed(device: dict, attribute: str) -> bool:
    """Whether a reading of ``attribute`` from ``device`` feeds crop-health.

    Attributes crop-health does not gate by medium are not governed here.
    """
    required = REQUIRED_MEDIUM.get(attribute)
    if required is None:
        return True
    medium = effective_medium(device, attribute)
    if medium == required:
        return True
    # ASSUMPTION: a solar-park device that declares air under the structure keeps feeding
    # the under-panel context (shade, under-panel stress), which never reaches open-air inputs.
    return medium == _UNDER_STRUCTURE and attribute in _AIR_METRICS and _park_owned(device)


def log_ignored(tenant_id: str, device_id: str, attribute: str, medium: str | None) -> None:
    logger.debug(
        "reading ignored (medium mismatch): tenant=%s device=%s attribute=%s medium=%s required=%s",
        tenant_id, device_id, attribute, medium, REQUIRED_MEDIUM.get(attribute),
    )


FetchDevice = Callable[[str, str], Awaitable["dict | None"]]


class DeviceMediumGate:
    """Async gate for webhook readings: fetches the Device (cached) and applies the rule."""

    def __init__(self, fetch_device: FetchDevice, ttl_s: float = 300.0, clock=time.monotonic):
        self._fetch = fetch_device
        self._ttl = ttl_s
        self._clock = clock
        self._cache: dict[tuple[str, str], tuple[float, dict]] = {}

    async def allows(self, tenant_id: str, device_id: str, attribute: str) -> bool:
        if attribute not in REQUIRED_MEDIUM:
            return True
        key = (tenant_id, device_id)
        now = self._clock()
        hit = self._cache.get(key)
        device = hit[1] if hit and now - hit[0] < self._ttl else None
        if device is None:
            try:
                device = await self._fetch(tenant_id, device_id)
            except Exception as exc:  # noqa: BLE001 -- fail-safe: no data rather than wrong data
                logger.warning(
                    "medium gate: device lookup failed, reading skipped: tenant=%s device=%s attribute=%s: %s",
                    tenant_id, device_id, attribute, exc,
                )
                return False
            if not isinstance(device, dict):
                logger.warning(
                    "medium gate: device not found, reading skipped: tenant=%s device=%s attribute=%s",
                    tenant_id, device_id, attribute,
                )
                return False
            self._cache[key] = (now, device)
        if reading_allowed(device, attribute):
            return True
        log_ignored(tenant_id, device_id, attribute, effective_medium(device, attribute))
        return False
