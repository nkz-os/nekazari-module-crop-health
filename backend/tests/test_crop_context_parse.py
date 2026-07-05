"""CropContext must accept bioorch soil.actual.depth_cm as a horizon range string."""
from app.schemas import CropContext


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
