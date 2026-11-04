"""Driver: one POST per installed tenant; a failing tenant never stops the rest."""
import pytest

from scripts import cron_work_alerts as cron


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_failing_tenant_does_not_stop_the_others(monkeypatch):
    seen = []

    async def fake(tenant, base_url, secret):
        seen.append(tenant)
        if tenant == "t1":
            raise ConnectionError("down")
        return {"emitted": 1, "resolved": 0, "unchanged": 0}

    monkeypatch.setattr(cron, "_post_tenant", fake)
    failed = await cron.run_tenants(["t1", "t2"], "http://self", "s")
    assert seen == ["t1", "t2"] and failed == 1
