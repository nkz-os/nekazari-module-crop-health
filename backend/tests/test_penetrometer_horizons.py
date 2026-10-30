"""get_penetrometer_data reads horizons.value[] (keyValues and normalized);
the entity root is a legacy fallback and only counts when it carries a depth."""
import pytest

from app.services import context_client


async def _run(entities, monkeypatch):
    class _Orion:
        def __init__(self, *a, **k):
            pass

        async def query_entities(self, **kw):
            return entities

        async def close(self):
            pass

    monkeypatch.setattr(context_client, "OrionClient", _Orion)
    return await context_client.get_penetrometer_data("parcel1", "tenant-a")


@pytest.mark.asyncio
async def test_reads_horizons_keyvalues(monkeypatch):
    out = await _run([{
        "id": "urn:ngsi-ld:SoilSamplingPoint:1",
        "horizons": [
            {"depthFrom": 0, "depthTo": 30, "penetrationResistance": 2.5},
            {"depthFrom": 30, "depthTo": 60, "penetrationResistance": 4.5},
        ],
    }], monkeypatch)
    assert out["available"] is True
    assert out["point_count"] == 2
    assert out["mean_mpa"] == pytest.approx(3.5)
    assert out["max_mpa"] == pytest.approx(4.5)
    assert "0-30" in out["depth_range"] and "30-60" in out["depth_range"]


@pytest.mark.asyncio
async def test_reads_horizons_normalized_and_single_unwrapped(monkeypatch):
    out = await _run([
        {"horizons": {"type": "Property", "value": [
            {"depthFrom": 0, "depthTo": 30, "penetrationResistance": 2.0}]}},
        {"horizons": {"type": "Property",
                      "value": {"depthFrom": 30, "depthTo": 60, "penetrationResistance": 4.0}}},
    ], monkeypatch)
    assert out["point_count"] == 2
    assert out["mean_mpa"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_legacy_root_with_depth(monkeypatch):
    out = await _run([{
        "penetrationResistance": {"type": "Property", "value": 3.1},
        "depthFrom": {"type": "Property", "value": 0},
        "depthTo": {"type": "Property", "value": 30},
    }], monkeypatch)
    assert out["point_count"] == 1
    assert out["mean_mpa"] == pytest.approx(3.1)
    assert out["depth_range"] == "0-30"


@pytest.mark.asyncio
async def test_legacy_root_without_depth_is_discarded(monkeypatch):
    out = await _run([{"penetrationResistance": {"type": "Property", "value": 3.1}}], monkeypatch)
    assert out is None


@pytest.mark.asyncio
async def test_horizon_reading_without_depth_is_discarded(monkeypatch):
    out = await _run([{"horizons": [{"penetrationResistance": 3.0}]}], monkeypatch)
    assert out is None


@pytest.mark.asyncio
async def test_none_when_no_readings(monkeypatch):
    out = await _run([{"horizons": [{"depthFrom": 0, "depthTo": 30, "ph": 7.2}]}], monkeypatch)
    assert out is None
