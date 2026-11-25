"""Suspended tenants are skipped; an unreachable platform skips nobody."""
import pytest
from nkz_platform_sdk import TenantInstallations
from nkz_platform_sdk.installations import InstalledTenantsUnavailable

from scripts import cron_scheduled_assessments, cron_work_alerts, cron_yield_forecasts
from scripts import scheduled_tenants as mod


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _platform(monkeypatch, enabled=(), disabled=(), not_installed=(), error=None, failures=None):
    calls = []

    async def no_wait(seconds):
        calls.append(seconds)

    async def fake(module_id):
        assert module_id == "crop-health"
        if error and (failures is None or len(calls) < failures):
            raise error
        return TenantInstallations(module_id, tuple(enabled), tuple(disabled), tuple(not_installed))

    monkeypatch.setattr(mod, "installed_tenants", fake)
    monkeypatch.setattr(mod.asyncio, "sleep", no_wait)
    return calls


@pytest.mark.anyio
async def test_a_fresh_pod_asks_again(monkeypatch):
    monkeypatch.setenv("SCHEDULED_TENANTS", "a,gone")
    waits = _platform(monkeypatch, enabled=["a"], error=InstalledTenantsUnavailable("x"), failures=2)
    assert await mod.scheduled_tenants() == ["a"] and waits == [2, 5]


@pytest.mark.anyio
async def test_only_suspended_tenants_are_dropped_and_order_is_kept(monkeypatch):
    monkeypatch.setenv("SCHEDULED_TENANTS", "d, gone ,b,a")
    _platform(monkeypatch, enabled=["a", "x"], disabled=["b"], not_installed=["d"])
    assert await mod.scheduled_tenants() == ["d", "b", "a"]


@pytest.mark.anyio
async def test_an_unreachable_platform_skips_nobody(monkeypatch):
    monkeypatch.setenv("SCHEDULED_TENANTS", "a,b")
    _platform(monkeypatch, error=InstalledTenantsUnavailable("down"))
    assert await mod.scheduled_tenants() == ["a", "b"]


@pytest.mark.anyio
async def test_an_answer_with_no_tenant_at_all_is_not_trusted(monkeypatch, capsys):
    monkeypatch.setenv("SCHEDULED_TENANTS", "a,b")
    _platform(monkeypatch)
    assert await mod.scheduled_tenants() == ["a", "b"]
    assert "nothing skipped" in capsys.readouterr().err


@pytest.mark.anyio
async def test_every_configured_tenant_may_be_suspended(monkeypatch):
    monkeypatch.setenv("SCHEDULED_TENANTS", "a,b")
    _platform(monkeypatch, enabled=["x"])
    assert await mod.scheduled_tenants() == []


@pytest.mark.anyio
async def test_nothing_configured_asks_nothing(monkeypatch):
    monkeypatch.delenv("SCHEDULED_TENANTS", raising=False)
    _platform(monkeypatch, error=AssertionError("asked"))
    assert await mod.scheduled_tenants() == []


def test_every_driver_uses_it():
    for driver in (cron_scheduled_assessments, cron_yield_forecasts, cron_work_alerts):
        assert driver.scheduled_tenants is mod.scheduled_tenants
