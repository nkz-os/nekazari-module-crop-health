"""setup-parcel registers a tenant-wide DeviceMeasurement subscription (idempotent)."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_activate_ensures_subscription_for_tenant():
    from app.api import setup

    ensure_all = AsyncMock(return_value={"created": 1, "skipped": 0, "errors": []})

    with patch.object(setup, "INTERNAL_SECRET", "s3cr3t"), \
         patch("app.api.setup.ModuleActivation") as MA, \
         patch("app.api.setup.SubscriptionRegistrar") as SR:
        MA.return_value.ensure_entities = AsyncMock(
            return_value={"created": 0, "skipped": 2, "errors": [], "entity_ids": []})
        MA.return_value.close = AsyncMock()
        SR.return_value.ensure_all = ensure_all

        body = setup.SetupParcelRequest(parcel_id="Parcela-4", tenant_id="t-1", action="activate")
        req = type("R", (), {"headers": {"X-Internal-Service-Secret": "s3cr3t"}, "client": None})()
        await setup.setup_parcel(req, body)  # type: ignore[arg-type]

    ensure_all.assert_awaited_once()
    assert ensure_all.await_args.args[0] == ["t-1"]
    sub_defs = SR.call_args.kwargs["subscriptions"]
    assert any(s["type"] == "DeviceMeasurement" for s in sub_defs)
