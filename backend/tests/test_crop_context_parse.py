"""CropContext must accept the BioOrchestrator crop-context JSON contract."""
import pytest

from app.schemas import CropContext
from app.services import context_client


def test_crop_context_parses_depth_cm_range_string():
    data = {
        "parcel_id": "urn:ngsi-ld:AgriParcel:t:1",
        "crop": {"eppo": "TRZAX", "name": "trigo"},
        "soil": {
            "actual": {
                "depth_cm": "0-5",
                "data_available": True,
                "ph": 6.5,
                "texture": "Loam",
                "source": "soilgrids",
            },
            "suitability": {
                "verdict": "suitable",
                "confidence": "high",
                "reason": "Within tolerance",
            },
        },
    }
    ctx = CropContext(**data)
    assert ctx.soil.actual.depth_cm == "0-5"
    assert ctx.soil.suitability.verdict == "suitable"


def test_crop_context_parses_bioorch_shaped_payload():
    """Full crop-context shape after soil slug + C.5 assess (post A+B+C fixes)."""
    data = {
        "parcel_id": "urn:ngsi-ld:AgriParcel:montiko:p1",
        "crop": {"eppo": "TRZAX", "name": "trigo", "scientific_name": "Triticum aestivum"},
        "soil": {
            "requirements": {
                "ph_min": 5.5,
                "ph_max": 7.5,
                "textures": ["Loam", "Silt loam"],
                "drainage": ["well_drained", "moderate"],
                "depth_min_cm": 30,
            },
            "actual": {
                "ph": 6.8,
                "texture": "Loam",
                "depth_cm": "0-30",
                "data_available": True,
                "source": "soilgrids",
            },
            "suitability": {
                "verdict": "suitable",
                "confidence": "high",
                "reason": "Within tolerance",
                "ph": {"value": 6.8, "min": 5.5, "max": 7.5, "verdict": "suitable"},
                "texture": {"value": "Loam", "preferred": ["Loam"], "verdict": "suitable"},
                "drainage": {"value": "well", "preferred": ["well_drained"], "verdict": "suitable"},
            },
        },
        "match_level": "species",
    }
    ctx = CropContext(**data)
    assert ctx.soil.requirements.drainage == ["well_drained", "moderate"]
    assert ctx.soil.suitability.verdict == "suitable"


@pytest.mark.asyncio
async def test_get_crop_context_forwards_tenant_headers(monkeypatch):
    captured: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "parcel_id": "urn:ngsi-ld:AgriParcel:t:1",
                "crop": {"eppo": "TRZAX", "name": "trigo"},
                "soil": {"suitability": {"verdict": "unknown", "confidence": "low"}},
            }

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            return _Resp()

    context_client._crop_context_cache.clear()
    monkeypatch.setattr(context_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(
        context_client.get_settings(), "bioorchestrator_url", "http://bio", raising=False
    )

    ctx = await context_client.get_crop_context(
        "urn:ngsi-ld:AgriParcel:t:1", tenant_id="montiko"
    )
    assert ctx is not None
    assert captured["headers"]["X-Tenant-ID"] == "montiko"
    assert captured["headers"]["X-User-ID"] == "crop-health-worker"
