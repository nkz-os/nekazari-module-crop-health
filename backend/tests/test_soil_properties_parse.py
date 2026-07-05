"""get_soil_properties must tolerate soil-module summary/point response shapes."""
import pytest

from app.services import context_client


def test_summary_data_source_empty_string():
    data = {"dataSource": ""}
    h = {"source": "soilgrids"}
    assert context_client._summary_data_source(data, h) == "soilgrids"


def test_summary_data_source_ngsi_property():
    data = {"dataSource": {"type": "Property", "value": "lab_analysis"}}
    assert context_client._summary_data_source(data, {}) == "lab_analysis"


@pytest.mark.asyncio
async def test_get_soil_properties_summary_empty_data_source(monkeypatch):
    """ORAINBAI shape: horizons present, dataSource is empty string."""
    context_client._soil_cache.clear()

    summary = {
        "horizons": [
            {
                "sand": 20,
                "clay": 10,
                "silt": 70,
                "organicCarbon": 4,
                "fieldCapacity": 0.258,
                "wiltingPoint": 0.067,
                "ksatSaturated": 7.57,
                "hydrologicGroup": "B",
                "usdaTextureClass": "silt-loam",
            }
        ],
        "dataSource": "",
    }

    class _Resp:
        status_code = 200

        def json(self):
            return summary

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, headers=None):
            return _Resp()

    monkeypatch.setattr(context_client.httpx, "AsyncClient", lambda **kw: _Client())

    soil = await context_client.get_soil_properties("da36ccd2-test", "montiko")
    assert soil.usda_texture_class == "silt-loam"
    assert soil.sand_pct == 20
    assert soil.source == "soilgrids"


@pytest.mark.asyncio
async def test_get_soil_properties_point_null_texture(monkeypatch):
    """LUCAS point/texture may return null sand/clay/silt — use defaults."""
    context_client._soil_cache.clear()

    async def _no_summary(*args, **kwargs):
        class _Resp:
            status_code = 404

            def json(self):
                return {}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def get(self, url, headers=None, params=None):
                return _Resp()

        return _Client()

    async def _coords(*args, **kwargs):
        return (42.64, -2.08)

    point_payload = {
        "texture": {
            "sand": None,
            "clay": None,
            "silt": None,
            "organicCarbon": None,
            "usdaTextureClass": "clay-loam",
        },
        "hydraulic": {
            "fieldCapacity": 0.341,
            "wiltingPoint": 0.198,
            "saturatedHydraulicConductivity": 2.18,
            "hydrologicGroup": "C",
        },
        "source": {"provider": "LUCAS-Texture"},
    }

    call_count = {"n": 0}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, headers=None, params=None):
            call_count["n"] += 1
            if "summary" in url:
                return type("R", (), {"status_code": 404, "json": lambda self: {}})()
            return type("R", (), {"status_code": 200, "json": lambda self: point_payload})()

    monkeypatch.setattr(context_client.httpx, "AsyncClient", lambda **kw: _Client())
    monkeypatch.setattr(context_client, "_resolve_parcel_coords", _coords)

    soil = await context_client.get_soil_properties("parcel-x", "montiko")
    assert soil.sand_pct == 40
    assert soil.usda_texture_class == "clay-loam"
    assert soil.source == "LUCAS-Texture"
