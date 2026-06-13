"""Regression: assessment publisher must send the tenant to Orion AS-IS.

The canonical tenant format is hyphenated and the SDK OrionClient sends it
verbatim. fiware_publisher._make_headers used to underscore the tenant
(`replace("-", "_")`), routing CropHealthAssessment writes to a phantom
tenant for hyphenated (paying) tenants — e.g. asociacion-allotarra ->
asociacion_allotarra.
"""

from app.services.fiware_publisher import _make_headers

HYPHEN_TENANT = "asociacion-allotarra"


def test_hyphen_tenant_preserved_in_orion_headers():
    headers = _make_headers(HYPHEN_TENANT)
    assert headers["NGSILD-Tenant"] == HYPHEN_TENANT
    assert headers["Fiware-Service"] == HYPHEN_TENANT


def test_no_underscore_introduced():
    headers = _make_headers("a-b-c-d")
    assert "_" not in headers["NGSILD-Tenant"]
    assert "_" not in headers["Fiware-Service"]
