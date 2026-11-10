"""Observed growth stage from the field notebook.

A scouting operation (``AgriParcelOperation``) may carry ``phenologicalStage``,
a BBCH code as a two-character string. The term can arrive bare, with the
``nkz:`` prefix or as the full IRI; the parcel link as ``hasAgriParcel`` or
``refAgriParcel``. Read through the SDK broker client; any failure gives an
empty list and a warning.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from nkz_platform_sdk.orion import OrionClient

from app.config import get_settings

logger = logging.getLogger(__name__)

_TERM = "phenologicalStage"
_SPELLINGS = (_TERM, f"nkz:{_TERM}", f"https://nkz-os.org/ns/{_TERM}")
_PAGE = 200
_MAX_PAGES = 5
# Same shape the API layer accepts for a parcel id; anything else never reaches a broker filter.
_PARCEL_ID = re.compile(r"^(urn:ngsi-ld:AgriParcel:)?[A-Za-z0-9._:-]{1,128}$")


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("value", value.get("@value"))
    return value


def _code(raw: Any) -> str | None:
    value = _plain(raw)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = f"{value:02d}"
    if isinstance(value, str) and len(value.strip()) == 2 and value.strip().isdigit():
        return value.strip()
    return None


def _day(raw: Any) -> date | None:
    """Calendar day as written in the timestamp: an offset must not move a note to another day."""
    raw = _plain(raw)
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None


async def fetch_observed_stages(tenant_id: str, parcel_id: str, since: date) -> list[dict]:
    """``[{"date": "YYYY-MM-DD", "bbch": "31"}]`` of the parcel's scouting notes since ``since``, oldest first."""
    if not isinstance(parcel_id, str) or not _PARCEL_ID.fullmatch(parcel_id):
        logger.warning("observed_stage: parcel id rejected tenant=%s — no notebook read", tenant_id)
        return []
    short = parcel_id.split(":")[-1] if parcel_id.startswith("urn:") else parcel_id
    urn = f"urn:ngsi-ld:AgriParcel:{short}"
    # Orion compares a DateTime through its @value, as a string: a day of margin, exact check below.
    lo = (since - timedelta(days=1)).isoformat()
    q = (f'operationType=="scouting";(hasAgriParcel=="{urn}"|refAgriParcel=="{urn}");'
         f'startedAt[@value]>="{lo}"')
    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    ops: list[dict] = []
    try:
        for page_no in range(_MAX_PAGES):
            page = await client.query_entities(type="AgriParcelOperation", q=q, limit=_PAGE,
                                               offset=page_no * _PAGE, options="keyValues")
            page = page or []
            ops.extend(o for o in page if isinstance(o, dict))
            if len(page) < _PAGE:
                break
    except Exception as exc:  # noqa: BLE001 — the status is served without observations
        logger.warning("observed_stage: notebook read failed tenant=%s parcel=%s: %s", tenant_id, urn, exc)
        return []
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass

    out: list[dict] = []
    for op in ops:
        raw = next((op[k] for k in _SPELLINGS if op.get(k) is not None), None)
        if raw is None:
            continue
        code, day = _code(raw), _day(op.get("startedAt"))
        if code is None or day is None:
            logger.debug("observed_stage: operation %s tenant=%s parcel=%s has no usable stage/date — skipped",
                           op.get("id"), tenant_id, urn)
            continue
        if day < since - timedelta(days=1):  # one day of tolerance against the sowing date
            continue
        out.append({"date": day.isoformat(), "bbch": code})
    return sorted(out, key=lambda o: (o["date"], o["bbch"]))
