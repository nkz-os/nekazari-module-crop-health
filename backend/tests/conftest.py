"""
Test fixtures and shared configuration.
"""

import os
import sys

# Ensure app package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_parcel_site_lookup(request, monkeypatch):
    """The stage-table request reads the parcel from the broker; tests that do not
    exercise that read must not wait on a real connection."""
    if request.module.__name__.endswith("test_parcel_site"):
        return

    from app.services import parcel_site

    async def _empty(parcel_id, tenant_id):
        return parcel_site.ParcelSite(None, None, None)

    monkeypatch.setattr(parcel_site, "resolve_parcel_site", _empty)


@pytest.fixture(autouse=True)
def _no_terrain_unit_lookup(monkeypatch):
    """Zone weather is crossed from weather-map terrain units read from the broker; tests that
    exercise it provide units, the others must not wait on a real connection."""
    from app.services import pipeline

    async def _none(*a, **k):
        return []

    monkeypatch.setattr(pipeline, "fetch_terrain_units", _none)


@pytest.fixture(autouse=True)
def _fresh_eo_cache():
    """Satellite observations are cached per target for a few minutes; each test starts empty."""
    from app.services import eo_reader

    eo_reader.clear_cache()
    yield
    eo_reader.clear_cache()


@pytest.fixture(autouse=True)
def _crop_on_every_parcel(request, monkeypatch):
    """The sensor path assesses only parcels with a crop, read from the broker; tests that
    exercise that read provide it, the others get one."""
    if request.module.__name__.endswith("test_agri_crop_read"):
        return

    from app.services import context_client

    async def _crop(parcel_id, tenant_id=""):
        return {"species": "TRZAX"}

    monkeypatch.setattr(context_client, "get_agri_crop", _crop)
