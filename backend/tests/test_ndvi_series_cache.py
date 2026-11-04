"""The season NDVI series is read from Orion once per parcel/zone per day."""
from __future__ import annotations

from datetime import date

import pytest

from app.services import pipeline
from tests.test_cwsi_day_store import DayRedis
from tests.test_post_maturity import (  # noqa: F401  (autouse fixtures keep this offline)
    GREEN_THEN_DROP, NOW, TABLE, _no_network, _offline_context, _ref, _series,
)
from app.schemas import StageTable


def _counting(series):
    calls = []

    async def _fetch(tenant_id, parcel_id, zone_urn, since):
        calls.append((parcel_id, zone_urn, since))
        return series

    return calls, _fetch


@pytest.mark.asyncio
async def test_series_cached_per_parcel_zone_and_day(monkeypatch):
    calls, fetch = _counting(_series(GREEN_THEN_DROP))
    monkeypatch.setattr(pipeline, "_fetch_ndvi_series", fetch)
    store = DayRedis()
    since = date(2026, 3, 1)
    first = await pipeline._season_ndvi_series(store, "acme", "p1", None, since, NOW)
    again = await pipeline._season_ndvi_series(store, "acme", "p1", None, since, NOW)
    assert first == again == _series(GREEN_THEN_DROP)
    assert len(calls) == 1
    await pipeline._season_ndvi_series(store, "acme", "p1", "urn:z1", since, NOW)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_empty_series_is_not_cached_and_no_store_still_fetches(monkeypatch):
    calls, fetch = _counting([])
    monkeypatch.setattr(pipeline, "_fetch_ndvi_series", fetch)
    store = DayRedis()
    since = date(2026, 3, 1)
    await pipeline._season_ndvi_series(store, "acme", "p1", None, since, NOW)
    await pipeline._season_ndvi_series(store, "acme", "p1", None, since, NOW)
    await pipeline._season_ndvi_series(None, "acme", "p1", None, since, NOW)
    assert len(calls) == 3
    assert store.json == {}


@pytest.mark.asyncio
async def test_stage_flags_use_the_cache(monkeypatch):
    calls, fetch = _counting(_series(GREEN_THEN_DROP))
    monkeypatch.setattr(pipeline, "_fetch_ndvi_series", fetch)
    store = DayRedis()
    for _ in range(2):
        flags, basis = await pipeline._resolve_stage_flags(
            _ref(), "maturity", StageTable(stages=dict(TABLE)), tenant_id="acme", parcel_id="p1",
            zone_urn=None, season_start="2026-03-01", now=NOW, cache=store,
        )
        assert basis == "gdd_ndvi" and flags.water_sensitive is False
    assert len(calls) == 1
