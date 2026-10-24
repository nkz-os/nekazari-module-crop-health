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
