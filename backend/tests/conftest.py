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
