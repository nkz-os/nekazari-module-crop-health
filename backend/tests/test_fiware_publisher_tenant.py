"""Regression: assessment publisher must hand Orion the tenant AS-IS.

The canonical tenant format is hyphenated; OrionClient sends NGSILD-Tenant
verbatim. An earlier _make_headers underscored the tenant, routing writes to a
phantom tenant for hyphenated (paying) tenants (asociacion-allotarra ->
asociacion_allotarra). This test pins that publish_assessment constructs
OrionClient with the tenant unchanged.
"""

from unittest.mock import patch

import pytest

from app.schemas import CropHealthAssessment

HYPHEN_TENANT = "asociacion-allotarra"


@pytest.mark.asyncio
async def test_publish_constructs_orionclient_with_tenant_as_is():
    captured = {}

    class _FakeClient:
        def __init__(self, tenant_id, *a, **k):
            captured["tenant"] = tenant_id
        async def upsert_entities_batch(self, entities):
            return {"upserted": 1, "errors": [], "entity_ids": [entities[0]["id"]]}
        async def close(self):
            pass

    import app.services.fiware_publisher as fp
    with patch.object(fp, "OrionClient", _FakeClient), \
         patch.object(CropHealthAssessment, "to_ngsi_ld",
                      return_value={"id": "urn:ngsi-ld:CropHealthAssessment:P1-latest",
                                    "type": "CropHealthAssessment"}):
        ok = await fp.publish_assessment(
            CropHealthAssessment.model_construct(id="urn:ngsi-ld:CropHealthAssessment:P1-latest"),
            tenant_id=HYPHEN_TENANT,
        )

    assert ok is True
    assert captured["tenant"] == HYPHEN_TENANT
    assert "_" not in captured["tenant"]
