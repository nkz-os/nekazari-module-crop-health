"""Focused test: _aggregate_parent_composite uses SDK OrionClient (Task 2d)."""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock


class _FakeOrionClient:
    """Minimal fake matching the SDK OrionClient surface used by the pipeline."""

    def __init__(self, *args, **kwargs):
        self.upserts = []
        self.closed = False

    async def query_entities(self, type=None, q=None, limit=100, options=None):
        if type == "AgriParcel":
            # Two children, both with area, both pointing at the parent.
            return [
                {"id": "urn:ngsi-ld:AgriParcel:child-a", "area": 10.0},
                {"id": "urn:ngsi-ld:AgriParcel:child-b", "area": 30.0},
            ]
        if type == "CropHealthAssessment":
            if "child-a" in q:
                return [{"compositeStressIndex": 20.0, "dominantStressor": "water"}]
            if "child-b" in q:
                return [{"compositeStressIndex": 60.0, "dominantStressor": "heat"}]
        return []

    async def upsert_entities_batch(self, entities):
        self.upserts.extend(entities)
        return {"upserted": len(entities), "errors": [], "entity_ids": []}

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_aggregate_parent_composite_area_weighted_upsert():
    from app.services import pipeline

    fake = _FakeOrionClient()
    mock_settings = MagicMock()
    mock_settings.orion_ld_url = "http://orion:1026"
    mock_settings.orion_ld_context = "http://ctx/context.json"
    mock_config = MagicMock()
    mock_config.get_settings.return_value = mock_settings

    with patch.dict("sys.modules", {"app.config": mock_config}), patch(
        "nkz_platform_sdk.orion.OrionClient", return_value=fake
    ):
        await pipeline._aggregate_parent_composite(
            "urn:ngsi-ld:AgriParcel:parent",
            "test-tenant",
            datetime(2026, 6, 14, tzinfo=timezone.utc),
        )

    # Area-weighted: (20*10 + 60*30) / 40 = 50.0
    assert fake.closed is True
    assert len(fake.upserts) == 1
    body = fake.upserts[0]
    assert body["compositeStressIndex"]["value"] == 50.0
    assert body["hasAgriParcel"]["object"] == "urn:ngsi-ld:AgriParcel:parent"
    assert body["phenologySource"]["value"] == "aggregated_from_2_children"


@pytest.mark.asyncio
async def test_aggregate_parent_composite_per_child_failure_skips_one():
    from app.services import pipeline

    class _FailingChildClient(_FakeOrionClient):
        async def query_entities(self, type=None, q=None, limit=100, options=None):
            if type == "CropHealthAssessment" and "child-b" in q:
                raise RuntimeError("boom")
            return await super().query_entities(type=type, q=q, limit=limit, options=options)

    fake = _FailingChildClient()
    mock_settings = MagicMock()
    mock_settings.orion_ld_url = "http://orion:1026"
    mock_settings.orion_ld_context = "http://ctx/context.json"
    mock_config = MagicMock()
    mock_config.get_settings.return_value = mock_settings

    with patch.dict("sys.modules", {"app.config": mock_config}), patch(
        "nkz_platform_sdk.orion.OrionClient", return_value=fake
    ):
        await pipeline._aggregate_parent_composite(
            "urn:ngsi-ld:AgriParcel:parent",
            "test-tenant",
            datetime(2026, 6, 14, tzinfo=timezone.utc),
        )

    # child-b skipped; only child-a (csi=20) counts. Weighted: 20*10/40 = 5.0
    assert fake.closed is True
    assert len(fake.upserts) == 1
    assert fake.upserts[0]["compositeStressIndex"]["value"] == 5.0
    assert fake.upserts[0]["phenologySource"]["value"] == "aggregated_from_1_children"
