"""Driver: a failing page or tenant never stops the remaining tenants."""
import pytest

from scripts import cron_scheduled_assessments as cron


@pytest.fixture
def anyio_backend():
    return "asyncio"


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
    assert seen == [None, str(cron.BATCH)]
    assert totals["written"] == 1 and totals["errors"][0]["error"] == "TimeoutError"


@pytest.mark.anyio
async def test_backend_down_gives_up_after_three_failures(monkeypatch):
    calls = []

    async def fake(tenant, cursor, base_url, secret):
        calls.append(cursor)
        raise ConnectionError("down")

    monkeypatch.setattr(cron, "_post_page", fake)
    totals = await cron.run_tenant("tenant-a", "http://self", "s")
    assert len(calls) == 3 and len(totals["errors"]) == 3


@pytest.mark.anyio
async def test_failing_tenant_does_not_stop_the_others_and_exit_is_non_zero(monkeypatch):
    done = []

    async def fake_run(tenant, base_url, secret):
        if tenant == "bad":
            raise RuntimeError("x")
        done.append(tenant)
        return {"processed": 0, "written": 0, "errors": []}

    monkeypatch.setattr(cron, "run_tenant", fake_run)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s")
    monkeypatch.setenv("SCHEDULED_TENANTS", "bad,good")
    with pytest.raises(SystemExit) as exc:
        await cron.main()
    assert exc.value.code == 1
    assert done == ["good"]


@pytest.mark.anyio
async def test_exit_is_one_when_every_page_raises(monkeypatch):
    async def fake(tenant, cursor, base_url, secret):
        raise ConnectionError("down")

    monkeypatch.setattr(cron, "_post_page", fake)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s")
    monkeypatch.setenv("SCHEDULED_TENANTS", "a,b")
    with pytest.raises(SystemExit) as exc:
        await cron.main()
    assert exc.value.code == 1


@pytest.mark.anyio
async def test_exit_is_zero_when_all_pages_succeed(monkeypatch):
    async def fake(tenant, cursor, base_url, secret):
        return {"processed": 1, "written": 1, "errors": [{"parcel_id": "p", "error": "x"}], "next_cursor": None}

    monkeypatch.setattr(cron, "_post_page", fake)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s")
    monkeypatch.setenv("SCHEDULED_TENANTS", "a")
    assert await cron.main() is None


@pytest.mark.anyio
async def test_connect_error_is_retried_before_the_page_fails(monkeypatch):
    import httpx

    calls = []

    async def once(tenant, cursor, base_url, secret):
        calls.append(cursor)
        if len(calls) < 3:
            raise httpx.ConnectError("All connection attempts failed")
        return {"processed": 1, "written": 1, "errors": [], "next_cursor": None}

    monkeypatch.setattr(cron, "_post_once", once)
    monkeypatch.setattr(cron, "CONNECT_RETRY_DELAYS_S", (0, 0, 0))
    page = await cron._post_page("tenant-a", None, "http://self", "s")
    assert page["written"] == 1 and calls == [None, None, None]


@pytest.mark.anyio
async def test_connect_error_gives_up_after_the_retries(monkeypatch):
    import httpx

    calls = []

    async def once(tenant, cursor, base_url, secret):
        calls.append(cursor)
        raise httpx.ConnectError("All connection attempts failed")

    monkeypatch.setattr(cron, "_post_once", once)
    monkeypatch.setattr(cron, "CONNECT_RETRY_DELAYS_S", (0, 0))
    with pytest.raises(httpx.ConnectError):
        await cron._post_page("tenant-a", None, "http://self", "s")
    assert len(calls) == 3


@pytest.mark.anyio
async def test_other_errors_are_not_retried(monkeypatch):
    import httpx

    calls = []

    async def once(tenant, cursor, base_url, secret):
        calls.append(cursor)
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(cron, "_post_once", once)
    monkeypatch.setattr(cron, "CONNECT_RETRY_DELAYS_S", (0, 0))
    with pytest.raises(httpx.ReadTimeout):
        await cron._post_page("tenant-a", None, "http://self", "s")
    assert len(calls) == 1
