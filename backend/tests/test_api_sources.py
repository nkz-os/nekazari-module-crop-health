"""Tests for GET /api/crop-health/sources endpoint."""
import pytest
from httpx import ASGITransport, AsyncClient
import respx

from app.main import app

# AuthMiddleware trusts gateway-injected identity headers
GATEWAY_HEADERS = {"X-Tenant-ID": "test-tenant", "X-User-ID": "test-user"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_sources_list_returns_empty_for_no_parcels():
    """When Orion-LD returns no parcels, list is empty."""
    with respx.mock as mock:
        # Mock all Orion-LD queries to return empty
        mock.get().respond(json=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources")
            assert resp.status_code == 200
            data = resp.json()
            assert "parcels" in data
            assert data["parcels"] == []


@pytest.mark.anyio
async def test_sources_list_with_assessment_data():
    """Parcels with assessments show health indicators."""
    with respx.mock as mock:
        # Route 1: Assessments query
        mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(json=[
            {
                "id": "urn:ngsi-ld:CropHealthAssessment:cha-1",
                "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:Parcela-4"},
                "cwsiValue": 0.42,
                "overallSeverity": "MEDIUM",
                "assessedAt": "2026-06-07T10:00:00Z",
                "dataFidelity": "onsite_uncalibrated",
            }
        ])
        # Route 2: Parcels query
        mock.get(url__regex=r".*type=AgriParcel.*").respond(json=[
            {"id": "urn:ngsi-ld:AgriParcel:Parcela-4", "name": "Parcela 4"},
            {"id": "urn:ngsi-ld:AgriParcel:Parcela-15", "name": "Parcela 15"},
        ])
        # Route 3: IoT devices query — one device for Parcela-4
        mock.get(url__regex=r".*type=DeviceMeasurement.*").respond(json=[
            {
                "id": "urn:ngsi-ld:DeviceMeasurement:Parcela-4-sensor1",
                "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:Parcela-4"},
                "leafTemperature": 28.4,
            }
        ])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["parcels"]) >= 2

            p4 = next(p for p in data["parcels"] if p["parcelId"] == "Parcela-4")
            assert p4["hasIot"] is True
            assert p4["healthIndicator"] in ("green", "blue", "yellow")

            p15 = next(p for p in data["parcels"] if p["parcelId"] == "Parcela-15")
            assert p15["hasIot"] is False


@pytest.mark.anyio
async def test_sources_detail_returns_source_status():
    """Detail endpoint returns per-source status for a single parcel."""
    with respx.mock as mock:
        mock.get(url__regex=r".*type=CropHealthAssessment.*hasAgriParcel.*").respond(json=[
            {
                "id": "urn:ngsi-ld:CropHealthAssessment:Parcela-4-20260607",
                "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:Parcela-4"},
                "cwsiValue": 0.42,
                "overallSeverity": "MEDIUM",
                "assessedAt": "2026-06-07T10:00:00Z",
                "dataFidelity": "onsite_uncalibrated",
                "soilTexture": "franco-arcilloso",
                "soilPh": 7.2,
                "soilAWCmm": 90.0,
                "phenologyStage": "flowering",
            }
        ])
        mock.get(url__regex=r".*type=DeviceMeasurement.*hasAgriParcel.*").respond(json=[
            {
                "id": "urn:ngsi-ld:DeviceMeasurement:Parcela-4-sensor1",
                "leafTemperature": 28.4,
                "dateObserved": "2026-06-07T10:25:00Z",
            }
        ])
        # Real VegetationIndex entities (vegetation module
        # fiware_integration.py) carry ndviMean/Min/Max/StdDev + sensingDate,
        # not ndviValue/dateObserved.
        mock.get(url__regex=r".*type=VegetationIndex.*hasAgriParcel.*").respond(json=[
            {
                "id": "urn:ngsi-ld:VegetationIndex:vi-1",
                "ndviMean": 0.72,
                "sensingDate": "2026-06-05T10:30:00Z",
            }
        ])
        mock.get(url__regex=r".*type=AgriCrop.*hasAgriParcel.*").respond(json=[
            {
                "id": "urn:ngsi-ld:AgriCrop:Parcela-4-2025-2026",
                "plantingDate": "2025-10-02",
                "species": "Triticum aestivum",
                "eppoCode": "TRZAX",
                "variety": "Gazul",
            }
        ])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources?parcelId=Parcela-4")
            assert resp.status_code == 200
            data = resp.json()
            assert data["parcelId"] == "Parcela-4"
            src = data["sources"]

            assert src["soil"]["status"] == "ok"
            assert src["soil"]["details"]["texture"] == "franco-arcilloso"
            assert src["iot"]["status"] == "ok"
            assert len(src["iot"]["sensors"]) >= 1
            assert src["satellite"]["ndvi"]["status"] == "ok"
            assert src["satellite"]["ndvi"]["lastValue"] == 0.72
            assert src["crop"]["status"] == "ok"
            assert src["crop"]["plantingDate"] == "2025-10-02"


@pytest.mark.anyio
async def test_sources_detail_no_data_parcel():
    """Parcel with no data gets unavailable status everywhere."""
    with respx.mock as mock:
        mock.get().respond(json=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources?parcelId=Parcela-99")
            assert resp.status_code == 200
            data = resp.json()
            assert data["parcelId"] == "Parcela-99"
            for key in ("soil", "iot", "weather", "crop", "bioorchestrator"):
                assert data["sources"][key]["status"] == "unavailable"
