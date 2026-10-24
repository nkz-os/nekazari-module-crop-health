"""Read the parcel URN out of a device's link attribute, in any form Orion returns."""

from __future__ import annotations


def _urn(item) -> str:
    if isinstance(item, dict):
        item = item.get("object") or item.get("value") or item.get("@id")
    return item if isinstance(item, str) else ""


def parcel_link_targets(link) -> list[str]:
    """Every URN a link attribute points at, in order (primary first).

    A Relationship carries ``object``; legacy entities stored as Property carry
    ``value``; keyValues gives a bare string. ``object`` may be a list when a
    device serves several parcels.
    """
    if isinstance(link, dict):
        link = link.get("object") or link.get("value")
    items = link if isinstance(link, list) else [link]
    return [u for u in (_urn(i) for i in items) if u]


def parcel_link_target(link) -> str:
    """The primary URN a link attribute points at, or ""."""
    targets = parcel_link_targets(link)
    return targets[0] if targets else ""


UNDER_PANEL = "under_panel"
OPEN_FIELD = "open_field"
PARK_PREFIX = "urn:ngsi-ld:AgriSolarPark:"
PARCEL_PREFIX = "urn:ngsi-ld:AgriParcel:"


def owner_from_link(link) -> tuple[str, str | None, str | None] | None:
    """Classify a device's owner from its ``controlledAsset`` link.

    The owner is the FIRST entry. Returns ``(context, parcel_urn, park_urn)``:
    a solar park owner is ``under_panel`` (parcel_urn is the first parcel listed
    after it, if any); a parcel owner is ``open_field``. None when the list is
    empty or the first entry is neither a park nor a parcel.
    """
    targets = parcel_link_targets(link)
    if not targets:
        return None
    first = targets[0]
    if first.startswith(PARK_PREFIX):
        parcel = next((t for t in targets[1:] if t.startswith(PARCEL_PREFIX)), None)
        return (UNDER_PANEL, parcel, first)
    if first.startswith(PARCEL_PREFIX):
        return (OPEN_FIELD, first, None)
    return None
