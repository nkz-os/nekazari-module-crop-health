"""Read the parcel URN out of a device's link attribute, in any form Orion returns."""

from __future__ import annotations


def parcel_link_target(link) -> str:
    """The URN a link attribute points at, or "".

    Orion-LD returns ``controlledAsset`` (declared ``@type: @id``) as a Property
    with a ``value``; a Relationship carries ``object``; keyValues gives a bare string.
    """
    if isinstance(link, dict):
        link = link.get("object") or link.get("value")
    return link if isinstance(link, str) else ""
