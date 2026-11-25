"""Tests for GET /api/crop-health/sources endpoint."""
import pytest
from httpx import ASGITransport, AsyncClient
import httpx
import respx

from app.main import app

# Gateway identity headers (signature check is off in tests; see test_gateway_auth.py)
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
    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with respx.mock as mock:
        # Route 1: Assessments query
        mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(json=[
            {
                "id": "urn:ngsi-ld:CropHealthAssessment:cha-1",
                "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:Parcela-4"},
                "cwsiValue": 0.42,
                "overallSeverity": "MEDIUM",
                "assessedAt": recent,
                "dataFidelity": "onsite_uncalibrated",
            }
        ])
        # Route 2: Parcels query
        mock.get(url__regex=r".*type=AgriParcel.*").respond(json=[
            {"id": "urn:ngsi-ld:AgriParcel:Parcela-4", "name": "Parcela 4"},
            {"id": "urn:ngsi-ld:AgriParcel:Parcela-15", "name": "Parcela 15"},
        ])
        # Route 3: IoT devices query — one Device for Parcela-4, linked by
        # controlledAsset (the canonical link; readings live in DeviceMeasurement)
        mock.get(url__regex=r".*type=Device(&|$|%).*").respond(json=[
            {
                "id": "urn:ngsi-ld:Device:test-tenant:sensor1",
                "controlledAsset": "urn:ngsi-ld:AgriParcel:Parcela-4",
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
async def test_sources_list_device_linked_to_several_parcels():
    """A device whose controlledAsset lists several parcels counts in each."""
    with respx.mock as mock:
        mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(json=[])
        mock.get(url__regex=r".*type=AgriParcel.*").respond(json=[
            {"id": "urn:ngsi-ld:AgriParcel:Parcela-4", "name": "Parcela 4"},
            {"id": "urn:ngsi-ld:AgriParcel:Parcela-15", "name": "Parcela 15"},
            {"id": "urn:ngsi-ld:AgriParcel:Parcela-20", "name": "Parcela 20"},
        ])
        mock.get(url__regex=r".*type=Device(&|$|%).*").respond(json=[
            {
                "id": "urn:ngsi-ld:Device:test-tenant:sensor1",
                "controlledAsset": ["urn:ngsi-ld:AgriParcel:Parcela-4", "urn:ngsi-ld:AgriParcel:Parcela-15"],
            }
        ])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources")
            assert resp.status_code == 200
            by_id = {p["parcelId"]: p for p in resp.json()["parcels"]}
            assert by_id["Parcela-4"]["hasIot"] is True
            assert by_id["Parcela-15"]["hasIot"] is True
            assert by_id["Parcela-20"]["hasIot"] is False


@pytest.mark.anyio
async def test_sources_list_park_owned_device_counts_for_parcel_only():
    """A park-first controlledAsset counts for its parcel and creates no park entry."""
    with respx.mock as mock:
        mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(json=[])
        mock.get(url__regex=r".*type=AgriParcel.*").respond(json=[
            {"id": "urn:ngsi-ld:AgriParcel:Parcela-4", "name": "Parcela 4"},
        ])
        mock.get(url__regex=r".*type=Device(&|$|%).*").respond(json=[
            {
                "id": "urn:ngsi-ld:Device:test-tenant:sensor1",
                "controlledAsset": ["urn:ngsi-ld:AgriSolarPark:x", "urn:ngsi-ld:AgriParcel:Parcela-4"],
            }
        ])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources")
            assert resp.status_code == 200
            parcels = resp.json()["parcels"]
            assert [p["parcelId"] for p in parcels] == ["Parcela-4"]
            assert parcels[0]["hasIot"] is True


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
        mock.get(url__regex=r".*type=Device(&|%).*").respond(json=[
            {
                "id": "urn:ngsi-ld:Device:test-tenant:sensor1",
                "controlledAsset": "urn:ngsi-ld:AgriParcel:Parcela-4",
                "observationContext": {"medium": "plant"},
            }
        ])
        mock.get(url__regex=r".*type=DeviceMeasurement.*").respond(json=[
            {
                "id": "urn:ngsi-ld:DeviceMeasurement:test-tenant:sensor1:leafTemperature",
                "refDevice": "urn:ngsi-ld:Device:test-tenant:sensor1",
                "controlledProperty": "leafTemperature",
                "numValue": 28.4,
                "dateObserved": "2026-06-07T10:25:00Z",
            }
        ])
        # Satellite products in the earlier stored shape (EOProduct): an optical one with
        # `ndvi`, and a newer and an older Sentinel-1 GRD one; none in the SDM shape.
        mock.get(url__regex=r".*type=EOSatelliteImagery.*").respond(json=[])
        mock.get(url__regex=r".*type=EOProduct.*").respond(json=[
            {
                "id": "urn:ngsi-ld:EOProduct:test-tenant:Parcela-4:2026-06-05",
                "type": "EOProduct",
                "hasAgriParcel": "urn:ngsi-ld:AgriParcel:Parcela-4",
                "sensingDate": "2026-06-05",
                "ndvi": 0.72,
            },
            {
                "id": "urn:ngsi-ld:EOProduct:test-tenant:Parcela-4:grd:2026-06-06",
                "type": "EOProduct",
                "hasAgriParcel": "urn:ngsi-ld:AgriParcel:Parcela-4",
                "productType": "GRD",
                "sensingDate": "2026-06-06",
                "backscatterVV": -9.5,
                "backscatterVH": -16.0,
            },
            {
                "id": "urn:ngsi-ld:EOProduct:test-tenant:Parcela-4:grd:2026-05-01",
                "type": "EOProduct",
                "hasAgriParcel": "urn:ngsi-ld:AgriParcel:Parcela-4",
                "productType": "GRD",
                "sensingDate": "2026-05-01",
                "backscatterVV": -8.0,
                "backscatterVH": -14.0,
            },
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
            # The metric name is the VALUE of controlledProperty, and the reading
            # comes from numValue — never from an attribute named after the metric.
            sensor = src["iot"]["sensors"][0]
            assert sensor["metric"] == "leafTemperature"
            assert sensor["lastValue"] == 28.4
            assert src["satellite"]["ndvi"]["status"] == "ok"
            assert src["satellite"]["ndvi"]["lastValue"] == 0.72
            # A satellite product has a day, not a time: none is invented.
            assert src["satellite"]["ndvi"]["lastDataAt"] == "2026-06-05"
            assert src["satellite"]["ndvi"]["freshness"] == "none"  # old day, parsed without error
            # The newest GRD, not whichever the broker listed first.
            assert src["satellite"]["sar"]["lastValue"] == -16.0
            assert src["satellite"]["sar"]["lastDataAt"] == "2026-06-06"
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


@pytest.mark.anyio
async def test_tenant_qualified_parcel_urns_still_match():
    """The parcel key must survive a tenant segment.

    Parcels exist in both shapes across the platform: `AgriParcel:{id}` and
    `AgriParcel:{tenant}:{id}`. Normalising the device link with
    `split(":")[-1]` drops the tenant and stops matching the parcel map built
    from the prefix — the parcel silently loses its IoT flag.
    """
    with respx.mock as mock:
        mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(json=[])
        mock.get(url__regex=r".*type=AgriParcel.*").respond(json=[
            {"id": "urn:ngsi-ld:AgriParcel:test-tenant:Parcela-4", "name": "Parcela 4"},
        ])
        mock.get(url__regex=r".*type=Device(&|$|%).*").respond(json=[
            {
                "id": "urn:ngsi-ld:Device:test-tenant:sensor1",
                "controlledAsset": "urn:ngsi-ld:AgriParcel:test-tenant:Parcela-4",
            }
        ])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources")
            assert resp.status_code == 200
            parcel = resp.json()["parcels"][0]
            assert parcel["parcelId"] == "test-tenant:Parcela-4"
            assert parcel["hasIot"] is True


@pytest.mark.anyio
async def test_sources_detail_skips_daily_weather_entity():
    """The closed-day series entity (dailySummary true) is not the parcel's live weather."""
    with respx.mock as mock:
        mock.get(url__regex=r".*type=WeatherObserved.*").respond(json=[
            {"id": "urn:ngsi-ld:WeatherObserved:test-tenant:parcel-Parcela-77-daily",
             "dailySummary": True, "tempMin": 3.1, "tempMax": 14.2},
            {"id": "urn:ngsi-ld:WeatherObserved:test-tenant:parcel-Parcela-77",
             "temperature": 12.5, "dateObserved": "2026-06-07T10:00:00Z"},
        ])
        mock.get().respond(json=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources?parcelId=Parcela-77")
            assert resp.status_code == 200
            weather = resp.json()["sources"]["weather"]
            assert weather["status"] == "ok"
            assert "12.5°C" in weather["summary"]


@pytest.mark.anyio
async def test_sources_detail_reads_air_temperature_alias():
    """temperature and airTemperature share one IRI; the broker may return either name."""
    with respx.mock as mock:
        mock.get(url__regex=r".*type=WeatherObserved.*").respond(json=[
            {"id": "urn:ngsi-ld:WeatherObserved:test-tenant:parcel-Parcela-78",
             "airTemperature": 9.5, "dateObserved": "2026-06-07T10:00:00Z"},
        ])
        mock.get().respond(json=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources?parcelId=Parcela-78")
            assert resp.status_code == 200
            assert "9.5°C" in resp.json()["sources"]["weather"]["summary"]


_parcel_seq = iter(range(1000))


async def _bio_soil_sources(assessment_fields):
    """Fetch /sources for a fresh parcel whose only data is one assessment.

    A new parcel id per call: the endpoint caches its response by parcel id.
    """
    pid = f"Parcela-w{next(_parcel_seq)}"
    with respx.mock as mock:
        mock.get(url__regex=r".*type=CropHealthAssessment.*hasAgriParcel.*").respond(json=[
            {
                "id": f"urn:ngsi-ld:CropHealthAssessment:{pid}-20260607",
                "assessedAt": "2026-06-07T10:00:00Z",
                **assessment_fields,
            }
        ])
        mock.get().respond(json=[])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get(f"/api/crop-health/sources?parcelId={pid}")
            assert resp.status_code == 200
            return resp.json()["sources"]


@pytest.mark.anyio
async def test_soil_summary_has_no_placeholders_when_fields_missing():
    src = await _bio_soil_sources({"soilTexture": "sandy-loam"})
    assert src["soil"]["summary"] == "sandy-loam"
    assert "?" not in src["soil"]["summary"]
    src = await _bio_soil_sources({"soilTexture": "sandy-loam", "soilAWCmm": 46})
    assert src["soil"]["summary"] == "sandy-loam · AWC 46mm"
    src = await _bio_soil_sources({"soilTexture": "sandy-loam", "soilPh": 6.5, "soilAWCmm": 46})
    assert src["soil"]["summary"] == "sandy-loam · pH 6.5 · AWC 46mm"


@pytest.mark.anyio
async def test_soil_summary_empty_when_nothing_present():
    src = await _bio_soil_sources({})
    assert src["soil"]["summary"] == ""
    assert src["soil"]["status"] == "unavailable"


@pytest.mark.anyio
async def test_bioorchestrator_generic_kc_is_flagged():
    src = await _bio_soil_sources({"phenologySource": "default", "kc": 0.85})
    assert src["bioorchestrator"]["details"]["generic"] is True
    assert src["bioorchestrator"]["summary"] == "generic"


@pytest.mark.anyio
async def test_bioorchestrator_real_kc_keeps_summary():
    src = await _bio_soil_sources({"phenologySource": "bioorchestrator", "kc": 1.1})
    assert src["bioorchestrator"]["details"]["generic"] is False
    assert src["bioorchestrator"]["summary"] == "Kc=1.1"


@pytest.mark.anyio
async def test_bioorchestrator_without_kc_uses_neutral_literal():
    src = await _bio_soil_sources({"phenologySource": "bioorchestrator"})
    assert src["bioorchestrator"]["summary"] == "no_parameters"


@pytest.mark.anyio
async def test_soil_summary_empty_without_texture_even_with_ph():
    src = await _bio_soil_sources({"soilPh": 6.5, "soilAWCmm": 46})
    assert src["soil"]["summary"] == "" and src["soil"]["status"] == "unavailable"


@pytest.mark.anyio
async def test_sources_detail_describes_the_latest_assessment():
    """The broker returns assessments oldest first: the panel must describe the newest one."""
    with respx.mock as mock:
        mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(json=[
            {
                "id": "urn:ngsi-ld:CropHealthAssessment:Parcela-61-20260606",
                "hasAgriParcel": "urn:ngsi-ld:AgriParcel:Parcela-61",
                "assessedAt": "2026-06-06T04:00:00Z",
                "phenologyStage": "vegetative",
            },
            {
                "id": "urn:ngsi-ld:CropHealthAssessment:Parcela-61-20260607",
                "refAgriParcel": "urn:ngsi-ld:AgriParcel:Parcela-61",
                "assessedAt": "2026-06-07T04:00:00Z",
                "soilTexture": "loam",
                "soilDataSource": "soilgrids",
                "soilAWCmm": 80.0,
                "phenologyStage": "flowering",
            },
        ])
        mock.get().respond(json=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources?parcelId=Parcela-61")
    assert resp.status_code == 200
    src = resp.json()["sources"]
    assert src["soil"]["status"] == "ok" and src["soil"]["details"]["texture"] == "loam"
    assert src["soil"]["lastDataAt"] == "2026-06-07T04:00:00Z"
    assert src["crop"]["phenologyStage"] == "flowering"


@pytest.mark.anyio
async def test_sources_detail_cache_is_per_tenant():
    transport = ASGITransport(app=app)
    with respx.mock as mock:
        mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(json=[{
            "id": "urn:ngsi-ld:CropHealthAssessment:Parcela-62-20260607",
            "hasAgriParcel": "urn:ngsi-ld:AgriParcel:Parcela-62",
            "assessedAt": "2026-06-07T04:00:00Z",
            "soilTexture": "loam",
        }])
        mock.get().respond(json=[])
        async with AsyncClient(transport=transport, base_url="http://test",
                               headers={"X-Tenant-ID": "tenant-a", "X-User-ID": "user-a"}) as client:
            first = await client.get("/api/crop-health/sources?parcelId=Parcela-62")
    with respx.mock as mock:
        mock.get().respond(json=[])
        async with AsyncClient(transport=transport, base_url="http://test",
                               headers={"X-Tenant-ID": "tenant-b", "X-User-ID": "user-b"}) as client:
            second = await client.get("/api/crop-health/sources?parcelId=Parcela-62")
    assert first.json()["sources"]["soil"]["status"] == "ok"
    assert second.json()["sources"]["soil"]["status"] == "unavailable"


_VEG_STATE = {"crop": {"present": True, "species": "TRZAX"}, "monitoring": "none",
              "period": {"start": "2026-03-01", "end": None}, "needs_activation": True,
              "continuous_by": [], "activation_roles": ["Farmer", "TenantAdmin"]}


async def _detail(pid, veg):
    from unittest.mock import AsyncMock, patch
    with respx.mock as mock, patch("app.api.sources.vegetation_monitoring.parcel_monitoring", veg):
        mock.get().respond(json=[])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                               headers=GATEWAY_HEADERS) as client:
            resp = await client.get(f"/api/crop-health/sources?parcelId={pid}")
    assert resp.status_code == 200
    return resp.json()["sources"]["satellite"]["ndvi"]


@pytest.mark.anyio
async def test_sources_detail_flags_a_crop_without_monitoring():
    from unittest.mock import AsyncMock
    ndvi = await _detail("Parcela-81", AsyncMock(return_value=_VEG_STATE))
    assert ndvi["reason"] == "not_monitored"
    assert ndvi["monitoring"] == {"state": "none", "needs_activation": True, "period_start": "2026-03-01",
                                  "activation_roles": ["Farmer", "TenantAdmin"]}


@pytest.mark.anyio
async def test_sources_detail_active_monitoring_shows_nothing_new_as_reason():
    from unittest.mock import AsyncMock
    state = {**_VEG_STATE, "monitoring": "active", "needs_activation": False}
    ndvi = await _detail("Parcela-82", AsyncMock(return_value=state))
    assert "reason" not in ndvi
    assert ndvi["monitoring"]["state"] == "active" and ndvi["monitoring"]["needs_activation"] is False


@pytest.mark.anyio
async def test_sources_detail_without_vegetation_is_as_before():
    from unittest.mock import AsyncMock
    ndvi = await _detail("Parcela-83", AsyncMock(return_value=None))
    assert "monitoring" not in ndvi and "reason" not in ndvi
    ndvi = await _detail("Parcela-84", AsyncMock(side_effect=RuntimeError("boom")))
    assert "monitoring" not in ndvi and "reason" not in ndvi


@pytest.mark.anyio
async def test_sources_detail_ignores_readings_of_the_wrong_medium():
    """A leaf reading from a soil-medium device, and from one with no medium, is not a source."""
    with respx.mock as mock:
        mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(json=[])
        mock.get(url__regex=r".*type=Device(&|%).*").respond(json=[
            {"id": "urn:ngsi-ld:Device:acme:soil1", "controlledAsset": "urn:ngsi-ld:AgriParcel:p1",
             "observationContext": {"medium": "soil"}},
            {"id": "urn:ngsi-ld:Device:acme:unset1", "controlledAsset": "urn:ngsi-ld:AgriParcel:p1"},
            {"id": "urn:ngsi-ld:Device:acme:leaf1", "controlledAsset": "urn:ngsi-ld:AgriParcel:p1",
             "observationContext": {"medium": "soil"},
             "channelOverrides": {"leafTemperature": {"observationContext": {"medium": "plant"}}}},
        ])

        def _m(device, metric, value):
            return {"id": f"urn:ngsi-ld:DeviceMeasurement:acme:{device}:{metric}",
                    "refDevice": f"urn:ngsi-ld:Device:acme:{device}",
                    "controlledProperty": metric, "numValue": value,
                    "dateObserved": "2026-06-07T10:25:00Z"}

        mock.get(url__regex=r".*type=DeviceMeasurement.*").respond(json=[
            _m("soil1", "leafTemperature", 99.0),
            _m("unset1", "soilMoisture", 20.0),
            _m("soil1", "soilMoisture", 31.0),
            _m("leaf1", "leafTemperature", 27.0),
        ])
        mock.get().respond(json=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources?parcelId=p1")
        assert resp.status_code == 200
        got = sorted((s["metric"], s["lastValue"]) for s in resp.json()["sources"]["iot"]["sensors"])
        assert got == [("leafTemperature", 27.0), ("soilMoisture", 31.0)]


@pytest.mark.anyio
async def test_sources_detail_pages_measurements_and_hides_derived_series():
    """60 readings over two pages: every base appears once, no window-statistic series."""
    dev_urn = "urn:ngsi-ld:Device:acme:d1"

    def _m(metric, value):
        return {"id": f"urn:ngsi-ld:DeviceMeasurement:acme:d1:{metric}", "refDevice": dev_urn,
                "controlledProperty": metric, "numValue": value,
                "dateObserved": "2026-06-07T10:25:00Z"}

    page1 = [_m("airTemperatureMin", 1.0)] + [_m(f"filler{i}", float(i)) for i in range(49)]
    page2 = [_m("airTemperature", 15.0), _m("airTemperatureMax", 20.0), _m("lonelyMax", 3.0)] + [
        _m(f"extra{i}", float(i)) for i in range(7)]
    with respx.mock as mock:
        mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(json=[])
        mock.get(url__regex=r".*type=Device(&|%).*").respond(json=[
            {"id": dev_urn, "controlledAsset": "urn:ngsi-ld:AgriParcel:p-paged",
             "observationContext": {"medium": "ambientAir"}},
        ])

        def _measurements(request):
            offset = int(request.url.params.get("offset", "0"))
            return httpx.Response(200, json=page1 if offset == 0 else page2 if offset == 50 else [])

        mock.get(url__regex=r".*type=DeviceMeasurement.*").mock(side_effect=_measurements)
        mock.get().respond(json=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources?parcelId=p-paged")
        assert resp.status_code == 200
        metrics = [s["metric"] for s in resp.json()["sources"]["iot"]["sensors"]]
        assert "airTemperature" in metrics
        assert "airTemperatureMin" not in metrics and "airTemperatureMax" not in metrics
        assert "lonelyMax" in metrics  # base absent on the device: kept
        assert sum(m.startswith("filler") for m in metrics) == 49
        assert sum(m.startswith("extra") for m in metrics) == 7


@pytest.mark.anyio
async def test_sources_sdm_shape_keys_by_channel_and_hides_derived_series():
    """SDM shape: controlledProperty is the catalogue property and name the channel. The
    Min/Max series of a device still hide behind their base channel, never merge into it."""
    dev_urn = "urn:ngsi-ld:Device:acme:d1"

    def _m(channel, prop, statistic, value):
        return {"id": f"urn:ngsi-ld:DeviceMeasurement:acme:d1:{channel}", "refDevice": dev_urn,
                "controlledProperty": prop, "name": channel, "measurementType": statistic,
                "numValue": value, "dateObserved": "2026-06-07T10:25:00Z"}

    with respx.mock as mock:
        mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(json=[])
        mock.get(url__regex=r".*type=Device(&|%).*").respond(json=[
            {"id": dev_urn, "controlledAsset": "urn:ngsi-ld:AgriParcel:p-sdm",
             "observationContext": {"medium": "ambientAir"}},
        ])
        mock.get(url__regex=r".*type=DeviceMeasurement.*").respond(json=[
            _m("airTemperatureMin", "airTemperature", "min", 1.0),
            _m("airTemperature", "airTemperature", "instant", 15.0),
            _m("airTemperatureMax", "airTemperature", "max", 20.0),
        ])
        mock.get().respond(json=[])

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/sources?parcelId=p-sdm")
        assert resp.status_code == 200
        got = [(s["metric"], s["lastValue"]) for s in resp.json()["sources"]["iot"]["sensors"]]
        assert got == [("airTemperature", 15.0)]


def test_freshness_of_a_bare_day():
    from datetime import datetime, timedelta, timezone

    from app.api.sources import _freshness

    today = datetime.now(timezone.utc).date()
    assert _freshness(today.isoformat()) == "fresh"
    assert _freshness((today - timedelta(days=1)).isoformat()) == "fresh"  # whole days: a day has no hour
    assert _freshness((today - timedelta(days=3)).isoformat()) == "stale"
    assert _freshness((today - timedelta(days=7)).isoformat()) == "stale"
    assert _freshness((today - timedelta(days=8)).isoformat()) == "none"
    assert _freshness((today - timedelta(days=30)).isoformat()) == "none"


async def _crop_source(agri_crop):
    with respx.mock as mock:
        mock.get(url__regex=r".*type=AgriCrop.*hasAgriParcel.*").respond(json=[agri_crop])
        mock.get().respond(json=[])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get(f"/api/crop-health/sources?parcelId={agri_crop['id'].rsplit(':', 1)[-1]}")
    return resp.json()["sources"]["crop"]


@pytest.mark.anyio
async def test_crop_code_comes_from_the_species_code():
    crop = await _crop_source({"id": "urn:ngsi-ld:AgriCrop:acme:code1", "species": "TRZAX"})
    assert (crop["status"], crop["eppoCode"]) == ("ok", "TRZAX")


@pytest.mark.anyio
async def test_crop_code_keeps_an_explicit_code_next_to_a_name():
    crop = await _crop_source({"id": "urn:ngsi-ld:AgriCrop:acme:code2", "species": "wheat", "eppoCode": "TRZAX"})
    assert (crop["species"], crop["eppoCode"]) == ("wheat", "TRZAX")


@pytest.mark.anyio
async def test_a_concept_url_is_not_a_crop_code():
    crop = await _crop_source({"id": "urn:ngsi-ld:AgriCrop:acme:code3",
                               "eppoCode": "http://aims.fao.org/aos/agrovoc/c_7951"})
    assert (crop["status"], crop["eppoCode"]) == ("unavailable", None)
