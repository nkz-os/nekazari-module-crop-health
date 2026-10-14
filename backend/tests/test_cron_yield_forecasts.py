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


@pytest.mark.anyio
async def test_page_error_skips_page_and_continues(monkeypatch):
    seen = []

    async def fake(tenant, cursor, base_url, secret):
        seen.append(cursor)
        if cursor is None:
            raise TimeoutError("slow parcel")
        return {"processed": 1, "written": 1, "errors": [], "next_cursor": None}

    monkeypatch.setattr(cron, "_post_page", fake)
    totals = await cron.run_tenant("tenant-a", "http://self", "s")
    assert seen == [None, "1"]
    assert totals["written"] == 1 and totals["errors"][0]["error"] == "TimeoutError"


@pytest.mark.anyio
async def test_one_tenant_failing_does_not_stop_others(monkeypatch):
    done = []

    async def fake_run(tenant, base_url, secret):
        if tenant == "bad":
            raise RuntimeError("x")
        done.append(tenant)
        return {"processed": 0, "written": 0, "errors": []}

    monkeypatch.setattr(cron, "run_tenant", fake_run)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s")
    monkeypatch.setenv("SCHEDULED_TENANTS", "bad,good")
    await cron.main()
    assert done == ["good"]


@pytest.mark.anyio
async def test_backend_down_gives_up_after_three_failures(monkeypatch):
    calls = []

    async def fake(tenant, cursor, base_url, secret):
        calls.append(cursor)
        raise ConnectionError("down")

    monkeypatch.setattr(cron, "_post_page", fake)
    totals = await cron.run_tenant("tenant-a", "http://self", "s")
    assert len(calls) == 3 and len(totals["errors"]) == 3
