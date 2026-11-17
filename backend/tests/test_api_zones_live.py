from unittest.mock import patch
"""GET /assessments/zones: only live zones, differsFromParcel, parcelValues."""
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.api.assessment_mapper import differs_from_parcel
from app.main import app

GATEWAY_HEADERS = {"X-Tenant-ID": "test-tenant", "X-User-ID": "test-user"}
PARCEL = "urn:ngsi-ld:AgriParcel:p-1"
POLY = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}


@pytest.fixture
def anyio_backend():
    return "asyncio"


_RANK = {"high": 1, "medium": 2, "low": 3, "critical": 4}


def _zone(level, parcel="p-1"):
    """Current-zoning level of a parcel (AgriManagementZone, keyValues)."""
    return {
        "id": f"urn:ngsi-ld:AgriManagementZone:{parcel}:abcdef12:L{_RANK[level]}",
        "type": "AgriManagementZone",
        "refAgriParcel": f"urn:ngsi-ld:AgriParcel:{parcel}",
        "zoneLevel": level,
        "zoneRank": _RANK[level],
        "areaHa": 1.0,
        "zoningRunId": "abcdef12" + "0" * 24,
        "zoningMethod": "vegetationIndexMultiDate",
        "dateZoned": {"@type": "DateTime", "@value": "2026-11-17T12:00:00Z"},
        "location": POLY,
    }


def _zone_assessment(zid, cwsi, composite, at="2026-10-25T10:00:00Z", vigor=0.6, parcel="p-1"):
    return {
        "id": f"urn:ngsi-ld:CropHealthZoneAssessment:{parcel}:{zid}:{at}",
        "hasAgriParcel": f"urn:ngsi-ld:AgriParcel:{parcel}",
        "zoneId": zid,
        "cwsiValue": cwsi,
        "compositeStressIndex": composite,
        "vigorIndex": vigor,
        "overallSeverity": "LOW",
        "assessedAt": at,
    }


def _parcel_assessment(parcel="p-1", cwsi=0.5):
    return {
        "id": f"urn:ngsi-ld:CropHealthAssessment:a-{parcel}",
        "hasAgriParcel": f"urn:ngsi-ld:AgriParcel:{parcel}",
        "cwsiValue": cwsi,
        "compositeStressIndex": 60,
        "vigorIndex": 0.6,
        "overallSeverity": "LOW",
        "assessedAt": "2026-10-25T09:00:00Z",
    }


def _mock_orion(mock, zones, zone_assessments, assessments):
    mock.get(url__regex=r".*type=AgriManagementZone.*").respond(json=zones)
    mock.get(url__regex=r".*type=CropHealthZoneAssessment.*").respond(json=zone_assessments)
    mock.get(url__regex=r".*type=CropHealthAssessment(&|$).*").respond(json=assessments)


async def _get():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
        return await client.get("/api/crop-health/assessments/zones", params={"parcelId": "p-1"})


@pytest.mark.anyio
async def test_zones_of_deleted_zone_ids_are_hidden_and_differs_flag_is_set():
    with respx.mock as mock:
        _mock_orion(
            mock,
            [_zone("high"), _zone("medium")],
            [
                _zone_assessment("high", 0.5, 61),
                _zone_assessment("medium", 0.8, 60),
                _zone_assessment("critical", 0.9, 90),
            ],
            [_parcel_assessment()],
        )
        resp = await _get()
    assert resp.status_code == 200
    data = resp.json()
    assert [z["zoneId"] for z in data["zones"]] == ["high", "medium"]
    assert [z["differsFromParcel"] for z in data["zones"]] == [False, True]
    assert data["isWholeParcel"] is False
    assert data["parcelValues"]["cwsiValue"] == 0.5
    assert data["parcelValues"]["compositeStressIndex"] == 60
    assert data["parcelValues"]["vigorIndex"] == 0.6
    assert data["parcelValues"]["overallSeverity"] == "LOW"


@pytest.mark.anyio
async def test_stale_assessment_of_deleted_zone_does_not_shadow_live_zone():
    """Filter happens before dedupe: only live zones survive, latest per zone wins."""
    with respx.mock as mock:
        _mock_orion(
            mock,
            [_zone("high")],
            [
                _zone_assessment("high", 0.5, 60, at="2026-10-24T10:00:00Z"),
                _zone_assessment("high", 0.52, 62, at="2026-10-25T10:00:00Z"),
                _zone_assessment("critical", 0.1, 5, at="2026-10-26T10:00:00Z"),
            ],
            [_parcel_assessment()],
        )
        data = (await _get()).json()
    assert [z["zoneId"] for z in data["zones"]] == ["high"]
    assert data["zones"][0]["cwsiValue"] == 0.52


@pytest.mark.anyio
async def test_parcel_without_current_zoning_is_whole_parcel():
    twi = {
        "id": "urn:ngsi-ld:AgriParcelZone:test-tenant:p-1:twi-1",
        "hasAgriParcel": PARCEL,
        "nkz:zoneId": "twi-1",
        "nkz:twiMean": 7.2,
        "nkz:centroid": [0.5, 0.5],
        "location": POLY,
    }
    with respx.mock as mock:
        mock.get(url__regex=r".*type=AgriParcelZone.*").respond(json=[twi])
        _mock_orion(
            mock,
            [],
            [_zone_assessment("twi-1", 0.9, 90)],
            [_parcel_assessment()],
        )
        data = (await _get()).json()
    assert data["isWholeParcel"] is True
    assert data["zones"] == []
    assert data["parcelValues"]["cwsiValue"] == 0.5


@pytest.mark.anyio
async def test_no_parcel_assessment_gives_empty_parcel_values():
    with respx.mock as mock:
        _mock_orion(mock, [_zone("high")], [_zone_assessment("high", 0.5, 60)], [])
        data = (await _get()).json()
    assert data["parcelValues"] == {}
    assert [z["zoneId"] for z in data["zones"]] == ["high"]
    assert data["zones"][0]["differsFromParcel"] is False


@pytest.mark.anyio
async def test_all_endpoint_hides_deleted_zones_and_flags_per_parcel():
    """Two parcels: p-1 has a deleted zone; p-2 has no parcel assessment."""
    p1_zones = [_zone("high"), _zone("medium")]
    p2_zones = [_zone("low", parcel="p-2")]
    zone_assessments = [
        _zone_assessment("high", 0.5, 61),
        _zone_assessment("medium", 0.8, 60),
        _zone_assessment("critical", 0.9, 90),
        _zone_assessment("low", 0.3, 20, parcel="p-2"),
    ]

    def zone_rows(request):
        import httpx
        return httpx.Response(200, json=p2_zones if "p-2" in str(request.url) else p1_zones)

    def parcel_rows(request):
        import httpx
        return httpx.Response(200, json=[_parcel_assessment()] if "p-2" not in str(request.url) else [])

    with respx.mock as mock:
        mock.get(url__regex=r".*type=AgriManagementZone.*").mock(side_effect=zone_rows)
        mock.get(url__regex=r".*type=CropHealthZoneAssessment.*").respond(json=zone_assessments)
        mock.get(url__regex=r".*type=CropHealthAssessment(&|$).*").mock(side_effect=parcel_rows)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/assessments/zones/all")
    assert resp.status_code == 200
    data = resp.json()
    assert [(z["parcelId"], z["zoneId"]) for z in data["zones"]] == [
        ("p-1", "high"), ("p-1", "medium"), ("p-2", "low"),
    ]
    flags = {z["zoneId"]: z["differsFromParcel"] for z in data["zones"]}
    assert flags == {"high": False, "medium": True, "low": False}
    assert data["parcelValues"]["p-1"]["cwsiValue"] == 0.5
    assert data["parcelValues"]["p-2"] == {}


@pytest.mark.anyio
async def test_all_endpoint_pages_zone_assessments_beyond_two_hundred():
    import httpx
    n = 250
    zones = [_zone("high")]
    rows = [_zone_assessment("high", 0.5, 61, at=f"2026-10-25T{i // 60:02d}:{i % 60:02d}:00Z") for i in range(n)]
    rows[-1]["cwsiValue"] = 0.77  # latest, beyond the first 200 rows

    def paged(request):
        off = int(request.url.params["offset"])
        lim = int(request.url.params["limit"])
        return httpx.Response(200, json=rows[off:off + lim])

    with respx.mock as mock, patch("app.api.assessments.ORION_PAGE_SIZE", 100):
        mock.get(url__regex=r".*type=AgriManagementZone.*").respond(json=zones)
        mock.get(url__regex=r".*type=CropHealthZoneAssessment.*").mock(side_effect=paged)
        mock.get(url__regex=r".*type=CropHealthAssessment(&|$).*").respond(json=[_parcel_assessment()])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=GATEWAY_HEADERS) as client:
            resp = await client.get("/api/crop-health/assessments/zones/all")
    assert resp.status_code == 200
    out = resp.json()["zones"]
    assert len(out) == 1 and out[0]["cwsiValue"] == 0.77


P = {"cwsiValue": 0.5, "compositeStressIndex": 60, "vigorIndex": 0.6, "overallSeverity": "LOW"}


@pytest.mark.parametrize(
    "zone,expected",
    [
        ({**P}, False),
        ({**P, "cwsiValue": 0.59}, False),
        ({**P, "cwsiValue": 0.6}, True),
        ({**P, "compositeStressIndex": 69}, False),
        ({**P, "compositeStressIndex": 50}, True),
        ({**P, "vigorIndex": 0.7}, True),
        ({**P, "vigorIndex": 0.65}, False),
        ({**P, "overallSeverity": "HIGH"}, True),
        ({**P, "sensorNearby": True}, True),
        ({**P, "cwsiValue": None, "vigorIndex": None}, False),
    ],
)
def test_differs_from_parcel_thresholds(zone, expected):
    assert differs_from_parcel(zone, P) is expected


def test_differs_from_parcel_missing_on_parcel_side_does_not_count():
    assert differs_from_parcel({**P, "cwsiValue": 0.9}, {"cwsiValue": None}) is False
    assert differs_from_parcel({**P}, {}) is False


@pytest.mark.anyio
async def test_sensor_nearby_zone_always_differs(monkeypatch):
    """A level with a located sensor inside reports sensorNearby and differs from the parcel."""
    from app.services import pipeline

    inner = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    outer = {"type": "Polygon", "coordinates": [[[-5, -5], [-5, 5], [5, 5], [5, -5], [-5, -5]],
                                                [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    high, medium = _zone("high"), _zone("medium")
    high["location"], medium["location"] = inner, outer

    async def _sensors(pid, tid, **kw):
        return [{"device_id": "d1", "lon": 0.5, "lat": 0.5}]

    monkeypatch.setattr(pipeline, "_gather_parcel_sensors", _sensors)
    with respx.mock as mock:
        _mock_orion(
            mock, [high, medium],
            [_zone_assessment("high", 0.5, 60), _zone_assessment("medium", 0.5, 60)],
            [_parcel_assessment()],
        )
        data = (await _get()).json()
    by_id = {z["zoneId"]: z for z in data["zones"]}
    assert by_id["high"]["sensorNearby"] is True and by_id["high"]["differsFromParcel"] is True
    assert by_id["medium"]["sensorNearby"] is False  # the sensor sits in the hole, not in this level
