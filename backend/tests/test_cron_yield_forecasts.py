"""Driver: page until the cursor is null, sum the totals."""
import pytest

from scripts import cron_yield_forecasts as cron


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_pages_until_cursor_null(monkeypatch):
    pages = iter([
        {"processed": 1, "written": 1, "errors": [], "next_cursor": "1"},
        {"processed": 1, "written": 0, "errors": [{"parcel_id": "b", "error": "x"}], "next_cursor": None},
    ])
    seen = []

    async def fake(tenant, cursor, base_url, secret):
        seen.append(cursor)
        return next(pages)

    monkeypatch.setattr(cron, "_post_page", fake)
    totals = await cron.run_tenant("tenant-a", "http://self", "s")
    assert seen == [None, "1"]
    assert totals == {"processed": 2, "written": 1, "errors": [{"parcel_id": "b", "error": "x"}]}
