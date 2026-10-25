"""Children are assessed as independent parcels: no parent composite unless enabled."""
from datetime import datetime, timezone

import pytest

from app.services import pipeline


class _Assessment:
    parcel_id = "child-a"
    cwsi = None
    mds = None
    phenology_source = "default"

    class overall_severity:
        value = "LOW"

    class recommended_action:
        value = "NO_ACTION"


async def _run(monkeypatch, enabled):
    calls = []

    async def _no_event(*a, **k):
        return None

    async def _aggregate(*a, **k):
        calls.append(a)

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def get_entity(self, *a, **k):
            return {"hasAgriParcel": "urn:ngsi-ld:AgriParcel:parent"}

        async def close(self):
            pass

    import nkz_platform_sdk.orion as orion_mod

    monkeypatch.setattr(orion_mod, "OrionClient", _Client)
    monkeypatch.setattr(pipeline, "_publish_redis_event", _no_event)
    monkeypatch.setattr(pipeline, "_aggregate_parent_composite", _aggregate)
    monkeypatch.setattr(pipeline.get_settings(), "parent_composite_enabled", enabled, raising=False)
    await pipeline._emit_assessment_side_effects(
        _Assessment(), "tenant-a", datetime(2026, 10, 25, tzinfo=timezone.utc), "vegetative"
    )
    return calls


@pytest.mark.asyncio
async def test_child_does_not_aggregate_parent_by_default(monkeypatch):
    assert await _run(monkeypatch, False) == []


@pytest.mark.asyncio
async def test_child_aggregates_parent_when_enabled(monkeypatch):
    assert len(await _run(monkeypatch, True)) == 1
