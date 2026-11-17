"""Driver: page until the cursor is null, sum the totals."""
import httpx
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
    assert totals == {"processed": 2, "written": 1, "errors": [{"parcel_id": "b", "error": "x"}], "failed_pages": 0}


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
    assert totals["failed_pages"] == 1


@pytest.mark.anyio
async def test_one_tenant_failing_does_not_stop_others(monkeypatch):
    done = []

    async def fake_run(tenant, base_url, secret):
        if tenant == "bad":
            raise RuntimeError("x")
        done.append(tenant)
        return {"processed": 0, "written": 0, "errors": []}

    async def ready(base_url):
        return True

    monkeypatch.setattr(cron, "_wait_ready", ready)
    monkeypatch.setattr(cron, "run_tenant", fake_run)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s")
    monkeypatch.setenv("SCHEDULED_TENANTS", "bad,good")
    with pytest.raises(SystemExit) as exc:
        await cron.main()
    assert exc.value.code == 1
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


@pytest.fixture
def no_sleep(monkeypatch):
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(cron, "_sleep", fake_sleep)
    return waits


@pytest.mark.anyio
async def test_connect_error_is_retried_then_succeeds(monkeypatch, no_sleep):
    calls = []

    async def once(tenant, cursor, base_url, secret):
        calls.append(cursor)
        if len(calls) < 3:
            raise httpx.ConnectError("refused")
        return {"processed": 1, "written": 1, "errors": [], "next_cursor": None}

    monkeypatch.setattr(cron, "_post_once", once)
    page = await cron._post_page("tenant-a", None, "http://self", "s")
    assert page["written"] == 1 and len(calls) == 3
    assert no_sleep == [2.0, 4.0]


@pytest.mark.anyio
async def test_connect_error_gives_up_after_the_last_delay(monkeypatch, no_sleep):
    async def once(tenant, cursor, base_url, secret):
        raise httpx.ConnectTimeout("no route")

    monkeypatch.setattr(cron, "_post_once", once)
    with pytest.raises(httpx.ConnectTimeout):
        await cron._post_page("tenant-a", None, "http://self", "s")
    assert no_sleep == [2.0, 4.0, 8.0]


@pytest.mark.anyio
async def test_a_request_that_reached_the_backend_is_not_retried(monkeypatch, no_sleep):
    calls = []

    async def once(tenant, cursor, base_url, secret):
        calls.append(cursor)
        raise httpx.ReadTimeout("slow parcel")

    monkeypatch.setattr(cron, "_post_once", once)
    with pytest.raises(httpx.ReadTimeout):
        await cron._post_page("tenant-a", None, "http://self", "s")
    assert len(calls) == 1 and no_sleep == []


@pytest.mark.anyio
async def test_exit_is_one_when_a_page_was_lost(monkeypatch):
    async def ready(base_url):
        return True

    async def fake_run(tenant, base_url, secret):
        lost = 1 if tenant == "tenant-a" else 0
        return {"processed": 1, "written": 1, "errors": [], "failed_pages": lost}

    seen = []

    async def spy_run(tenant, base_url, secret):
        seen.append(tenant)
        return await fake_run(tenant, base_url, secret)

    monkeypatch.setattr(cron, "_wait_ready", ready)
    monkeypatch.setattr(cron, "run_tenant", spy_run)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s")
    monkeypatch.setenv("SCHEDULED_TENANTS", "tenant-a,tenant-b")
    with pytest.raises(SystemExit) as exc:
        await cron.main()
    assert exc.value.code == 1
    assert seen == ["tenant-a", "tenant-b"]   # the second tenant still ran


@pytest.mark.anyio
async def test_exit_is_zero_when_no_page_was_lost(monkeypatch):
    async def ready(base_url):
        return True

    async def fake_run(tenant, base_url, secret):
        return {"processed": 1, "written": 0, "errors": [{"parcel_id": "p", "error": "x"}], "failed_pages": 0}

    monkeypatch.setattr(cron, "_wait_ready", ready)
    monkeypatch.setattr(cron, "run_tenant", fake_run)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s")
    monkeypatch.setenv("SCHEDULED_TENANTS", "tenant-a")
    await cron.main()   # returns, no SystemExit


@pytest.mark.anyio
async def test_backend_never_ready_exits_one_without_posting(monkeypatch):
    async def never(base_url):
        return False

    async def must_not_run(tenant, base_url, secret):
        raise AssertionError("no page may be posted")

    monkeypatch.setattr(cron, "_wait_ready", never)
    monkeypatch.setattr(cron, "run_tenant", must_not_run)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s")
    monkeypatch.setenv("SCHEDULED_TENANTS", "tenant-a")
    with pytest.raises(SystemExit) as exc:
        await cron.main()
    assert exc.value.code == 1


@pytest.mark.anyio
async def test_wait_ready_polls_until_health_answers(monkeypatch, no_sleep):
    answers = iter([httpx.ConnectError("refused"), 503, 200])

    async def fake_get(url):
        nxt = next(answers)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr(cron, "_health_status", fake_get)
    assert await cron._wait_ready("http://self") is True
    assert no_sleep == [3.0, 3.0]


def test_connecting_times_out_fast_while_a_running_page_may_take_minutes():
    assert cron.REQUEST_TIMEOUT.connect == 10.0
    assert cron.REQUEST_TIMEOUT.read == 340.0
