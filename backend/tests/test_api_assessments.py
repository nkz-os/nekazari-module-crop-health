"""Tests for assessment_mapper and assessments API."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.api.assessment_mapper import (
    map_entity_to_assessment,
    map_entity_to_zone_assessment,
    dedupe_latest_per_parcel,
    dedupe_latest_per_zone,
)


SAMPLE_ENTITY = {
    "id": "urn:ngsi-ld:CropHealthAssessment:parcel-a-20260628",
    "type": "CropHealthAssessment",
    "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:parcel-a"},
    "assessedAt": "2026-06-28T10:00:00Z",
    "cwsiValue": 0.45,
    "overallSeverity": "MEDIUM",
    "recommendedAction": "MONITOR",
    "compactionRiskLevel": "moderate",
    "compactionRiskScore": 55,
    "compactionAdvisory": "compaction.advisory.monitor_susceptible_soil",
    "soilWaterMm": 80,
    "soilAWCmm": 120,
    "soilWaterRatio": 0.67,
    "vhi": 42.5,
    "vci": 38.0,
    "phenologyDeviation": "on_track",
    "stageProgressPct": 65.0,
    "gddAccumulated": 890,
}

SAMPLE_ZONE_ENTITY = {
    **SAMPLE_ENTITY,
    "id": "urn:ngsi-ld:CropHealthZoneAssessment:parcel-a-z1-20260628",
    "type": "CropHealthZoneAssessment",
    "zoneId": "z1",
    "hasAgriParcelZone": {
        "type": "Relationship",
        "object": "urn:ngsi-ld:AgriParcelZone:t:parcel-a:z1",
    },
}

_PARCEL_GEOM = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
}


class TestAssessmentMapper:
    def test_maps_compaction_and_nested_objects(self):
        result = map_entity_to_assessment(SAMPLE_ENTITY)
        assert result["parcelId"] == "parcel-a"
        assert result["compactionRiskLevel"] == "moderate"
        assert result["compactionRisk"]["advisory"] == "monitor_susceptible_soil"
        assert result["soilWaterBalance"]["swMm"] == 80
        assert result["vhi"]["vhi"] == 42.5
        assert result["phenologyDeviation"] == "on_track"
        assert result["gddAccumulated"] == 890

    def test_dedupe_latest_per_parcel(self):
        older = {**SAMPLE_ENTITY, "assessedAt": "2026-06-27T10:00:00Z"}
        newer = {**SAMPLE_ENTITY, "assessedAt": "2026-06-28T10:00:00Z"}
        other = {
            **SAMPLE_ENTITY,
            "id": "urn:ngsi-ld:CropHealthAssessment:parcel-b-20260628",
            "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:parcel-b"},
        }
        result = dedupe_latest_per_parcel([older, newer, other])
        assert len(result) == 2
        by_parcel = {map_entity_to_assessment(e)["parcelId"]: e for e in result}
        assert by_parcel["parcel-a"]["assessedAt"] == "2026-06-28T10:00:00Z"

    def test_dedupe_latest_per_zone(self):
        older = {**SAMPLE_ZONE_ENTITY, "assessedAt": "2026-06-27T10:00:00Z"}
        newer = {**SAMPLE_ZONE_ENTITY, "assessedAt": "2026-06-28T10:00:00Z"}
        other = {
            **SAMPLE_ZONE_ENTITY,
            "id": "urn:ngsi-ld:CropHealthZoneAssessment:parcel-a-z2-20260628",
            "zoneId": "z2",
            "hasAgriParcelZone": {"object": "urn:ngsi-ld:AgriParcelZone:t:parcel-a:z2"},
        }
        result = dedupe_latest_per_zone([older, newer, other])
        assert len(result) == 2
        by_zone = {map_entity_to_zone_assessment(e)["zoneId"]: e for e in result}
        assert by_zone["z1"]["assessedAt"] == "2026-06-28T10:00:00Z"

    def test_map_zone_assessment_includes_geometry(self):
        result = map_entity_to_zone_assessment(
            SAMPLE_ZONE_ENTITY,
            geometry=_PARCEL_GEOM,
            sensor_nearby=True,
        )
        assert result["zoneId"] == "z1"
        assert result["zoneUrn"] == "urn:ngsi-ld:AgriParcelZone:t:parcel-a:z1"
        assert result["geometry"]["type"] == "Polygon"
        assert result["sensorNearby"] is True


@pytest.fixture
def client():
    with patch("app.services.redis_state.RedisState.create", AsyncMock()), \
         patch("app.services.redis_state.RedisState.health_check", AsyncMock(return_value={"redis": "connected"})):
        from app.main import app
        c = TestClient(app)
        c.headers.update({"X-Tenant-ID": "test-tenant", "X-User-ID": "test-user"})
        return c


class TestAssessmentsAPI:
    def test_latest_empty(self, client):
        with patch(
            "app.api.assessments._fetch_assessment_entities",
            AsyncMock(return_value=[]),
        ), patch(
            "app.api.assessments._fetch_parcel_names",
            AsyncMock(return_value={}),
        ):
            resp = client.get("/api/crop-health/assessments/latest")
            assert resp.status_code == 200
            assert resp.json() == {"assessments": []}

    def test_latest_filters_parcel_id(self, client):
        with patch(
            "app.api.assessments._fetch_assessment_entities",
            AsyncMock(return_value=[SAMPLE_ENTITY]),
        ), patch(
            "app.api.assessments._fetch_parcel_names",
            AsyncMock(return_value={"parcel-a": "Parcela A"}),
        ):
            resp = client.get("/api/crop-health/assessments/latest?parcelId=parcel-a")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["assessments"]) == 1
            assert data["assessments"][0]["parcelId"] == "parcel-a"
            assert data["assessments"][0]["compactionRiskLevel"] == "moderate"

    def test_latest_resolves_parcel_name(self, client):
        with patch(
            "app.api.assessments._fetch_assessment_entities",
            AsyncMock(return_value=[SAMPLE_ENTITY]),
        ), patch(
            "app.api.assessments._fetch_parcel_names",
            AsyncMock(return_value={"parcel-a": "Parcela A"}),
        ):
            resp = client.get("/api/crop-health/assessments/latest")
            assert resp.status_code == 200
            data = resp.json()
            assert data["assessments"][0]["parcelId"] == "parcel-a"
            assert data["assessments"][0]["parcelName"] == "Parcela A"

    def test_assessments_all_alias(self, client):
        with patch(
            "app.api.assessments._fetch_assessment_entities",
            AsyncMock(return_value=[SAMPLE_ENTITY]),
        ), patch(
            "app.api.assessments._fetch_parcel_names",
            AsyncMock(return_value={}),
        ):
            resp = client.get("/api/crop-health/assessments/all")
            assert resp.status_code == 200
            assert len(resp.json()["assessments"]) == 1

    def test_correlation_stats(self, client):
        with patch(
            "app.api.assessments.OrionClient",
        ) as mock_cls, patch("httpx.AsyncClient") as mock_http:
            inst = AsyncMock()
            inst.query_entities = AsyncMock(return_value=[])
            inst.close = AsyncMock()
            mock_cls.return_value = inst

            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value={"data": []})
            mock_http.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)

            resp = client.get("/api/crop-health/assessments/correlation?parcelId=parcel-a")
            assert resp.status_code == 200
            body = resp.json()
            assert "pairs" in body
            assert "stats" in body
            assert body["stats"]["n"] == 0

    def test_export_csv(self, client):
        with patch("app.api.assessments.OrionClient") as mock_cls:
            inst = AsyncMock()
            inst.query_entities = AsyncMock(return_value=[])
            inst.close = AsyncMock()
            mock_cls.return_value = inst
            resp = client.get("/api/crop-health/assessments/export")
            assert resp.status_code == 200
            assert "text/csv" in resp.headers["content-type"]

    def test_disease_risks_empty(self, client):
        with patch("app.api.assessments.OrionClient") as mock_cls:
            inst = AsyncMock()
            inst.query_entities = AsyncMock(return_value=[])
            inst.close = AsyncMock()
            mock_cls.return_value = inst
            resp = client.get("/api/crop-health/diseases/active")
            assert resp.status_code == 200
            assert resp.json() == {"risks": []}

    def test_disease_risks_maps_alerts(self, client):
        disease_alert = {
            "id": "urn:ngsi-ld:Alert:montiko:disease:powdery_mildew-da36ccd2",
            "type": "Alert",
            "alertType": "powdery_mildew",
            "category": "disease",
            "severity": "high",
            "confidence": 0.9,
            "evaluationData": {
                "disease": "powdery_mildew",
                "crop": "grapevine",
                "conditions": "T > 25C for 3 days",
                "source_model": "Gubler-Thomas (UC Davis Powdery Mildew Risk Index)",
                "recommended_action": "Monitor and consider sulfur application",
            },
            "refEntity": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:da36ccd2"},
            "status": "active",
        }
        non_disease_alert = {
            "id": "urn:ngsi-ld:Alert:montiko:gdd_pest-da36ccd2",
            "type": "Alert",
            "alertType": "gdd_pest",
            "category": "agronomic",
            "severity": "high",
            "refEntity": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:da36ccd2"},
        }
        with patch("app.api.assessments.OrionClient") as mock_cls:
            inst = AsyncMock()
            inst.query_entities = AsyncMock(return_value=[disease_alert, non_disease_alert])
            inst.close = AsyncMock()
            mock_cls.return_value = inst
            resp = client.get("/api/crop-health/diseases/active")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["risks"]) == 1
            r = body["risks"][0]
            assert r["disease"] == "powdery_mildew"
            assert r["risk_level"] == "HIGH"
            assert r["crop"] == "grapevine"
            assert r["conditions"] == "T > 25C for 3 days"
            assert r["parcelId"] == "da36ccd2"
            assert r["source_model"].startswith("Gubler-Thomas")
            assert r["confidence"] == "high"

    def test_disease_risks_coerces_threshold_conditions(self, client):
        threshold_alert = {
            "id": "urn:ngsi-ld:Alert:montiko:botrytis-p1",
            "type": "Alert",
            "alertType": "botrytis",
            "category": "disease",
            "severity": "medium",
            "confidence": 0.7,
            "evaluationData": {
                "factors": ["lwd_hours_ok: 9.0", "temp_ok: 18.0C"],
                "conditions": [
                    {"logical_operator": "OR", "conditions": [
                        {"source": "leaf_wetness", "attribute": "hours", "operator": ">", "value": 8},
                    ]},
                ],
            },
            "refEntity": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:p1"},
            "status": "active",
        }
        with patch("app.api.assessments.OrionClient") as mock_cls:
            inst = AsyncMock()
            inst.query_entities = AsyncMock(return_value=[threshold_alert])
            inst.close = AsyncMock()
            mock_cls.return_value = inst
            resp = client.get("/api/crop-health/diseases/active")
            assert resp.status_code == 200
            r = resp.json()["risks"][0]
            assert isinstance(r["conditions"], str)
            assert r["conditions"] == "lwd_hours_ok: 9.0; temp_ok: 18.0C"
            assert r["disease"] == "botrytis"

    def test_zone_assessments_requires_parcel(self, client):
        resp = client.get("/api/crop-health/assessments/zones")
        assert resp.status_code == 200
        assert resp.json() == {"zones": [], "isWholeParcel": True}

    def test_zone_assessments_for_parcel(self, client):
        with patch(
            "app.api.assessments._fetch_zone_assessment_entities",
            AsyncMock(return_value=[SAMPLE_ZONE_ENTITY]),
        ), patch(
            "app.api.assessments.resolve_zones",
            AsyncMock(return_value=[]),
        ), patch(
            "app.api.assessments.is_whole_parcel",
            return_value=False,
        ), patch(
            "app.api.assessments._map_zone_entities_with_geometry",
            AsyncMock(return_value=([
                map_entity_to_zone_assessment(SAMPLE_ZONE_ENTITY, geometry=_PARCEL_GEOM),
            ], False)),
        ):
            resp = client.get("/api/crop-health/assessments/zones?parcelId=parcel-a")
            assert resp.status_code == 200
            body = resp.json()
            assert body["isWholeParcel"] is False
            assert len(body["zones"]) == 1
            assert body["zones"][0]["zoneId"] == "z1"

    def test_zone_assessments_all(self, client):
        with patch(
            "app.api.assessments._fetch_zone_assessment_entities",
            AsyncMock(return_value=[SAMPLE_ZONE_ENTITY]),
        ), patch(
            "app.api.assessments._map_zone_entities_with_geometry",
            AsyncMock(return_value=([
                map_entity_to_zone_assessment(SAMPLE_ZONE_ENTITY, geometry=_PARCEL_GEOM),
            ], False)),
        ):
            resp = client.get("/api/crop-health/assessments/zones/all")
            assert resp.status_code == 200
            assert len(resp.json()["zones"]) == 1


class TestHistory:
    def test_forwards_auth_and_range(self, client):
        with patch("httpx.AsyncClient") as mock_http:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value={"data": [
                {"observed_at": "2026-09-02T10:00:00Z", "cwsiValue": 0.2,
                 "compositeStressIndex": 0.31, "overallSeverity": "LOW"},
                {"observed_at": "2026-09-01T10:00:00Z", "cwsiValue": 0.1,
                 "compositeStressIndex": 0.12, "overallSeverity": "LOW"},
            ]})
            get = AsyncMock(return_value=mock_resp)
            mock_http.return_value.__aenter__.return_value.get = get

            resp = client.get(
                "/api/crop-health/assessments/history",
                params={"parcelId": "parcel-a", "from": "2026-09-01", "to": "2026-10-01"},
                headers={"Authorization": "Bearer tok", "X-Auth-Signature": "sig:1"},
            )

        assert resp.status_code == 200
        kwargs = get.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == "Bearer tok"
        assert kwargs["headers"]["X-Tenant-ID"] == "test-tenant"
        assert kwargs["headers"]["X-Auth-Signature"] == "sig:1"
        assert kwargs["params"]["from"].startswith("2026-09-01")
        assert kwargs["params"]["to"].startswith("2026-10-01")
        assert "compositeStressIndex" in kwargs["params"]["attrs"]
        pts = resp.json()["points"]
        assert [p["date"][:10] for p in pts] == ["2026-09-01", "2026-09-02"]
        assert pts[1]["composite"] == 0.31 and pts[1]["severity"] == "LOW"

    def test_days_without_from(self, client):
        with patch("httpx.AsyncClient") as mock_http:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value={"data": []})
            get = AsyncMock(return_value=mock_resp)
            mock_http.return_value.__aenter__.return_value.get = get
            client.get("/api/crop-health/assessments/history?parcelId=parcel-a&days=7")
        assert "from" in get.call_args.kwargs["params"]
        assert "to" not in get.call_args.kwargs["params"]

    def test_to_is_inclusive_and_bad_date_rejected(self, client):
        with patch("httpx.AsyncClient") as mock_http:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value={"data": []})
            get = AsyncMock(return_value=mock_resp)
            mock_http.return_value.__aenter__.return_value.get = get
            ok = client.get("/api/crop-health/assessments/history?parcelId=p&from=2026-09-01&to=2026-10-01")
            bad = client.get("/api/crop-health/assessments/history?parcelId=p&from=not-a-date")
        assert ok.status_code == 200
        assert get.call_args.kwargs["params"]["from"] == "2026-09-01T00:00:00Z"
        assert get.call_args.kwargs["params"]["to"] == "2026-10-01T23:59:59.999999Z"
        assert bad.status_code == 422

    def test_does_not_forward_absent_headers(self, client):
        with patch("httpx.AsyncClient") as mock_http:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value={"data": []})
            get = AsyncMock(return_value=mock_resp)
            mock_http.return_value.__aenter__.return_value.get = get
            client.get("/api/crop-health/assessments/history?parcelId=parcel-a")
        headers = get.call_args.kwargs["headers"]
        assert "Authorization" not in headers
        assert "X-Auth-Signature" not in headers

    def test_reader_error_logs_status_and_returns_empty(self, client, caplog):
        import httpx

        with patch("httpx.AsyncClient") as mock_http:
            req = httpx.Request("GET", "http://reader/x")
            err = httpx.HTTPStatusError(
                "401", request=req, response=httpx.Response(401, request=req)
            )
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock(side_effect=err)
            get = AsyncMock(return_value=mock_resp)
            mock_http.return_value.__aenter__.return_value.get = get
            with caplog.at_level("ERROR", logger="app.api.assessments"):
                resp = client.get("/api/crop-health/assessments/history?parcelId=parcel-a")
        assert resp.status_code == 200
        assert resp.json() == {"points": []}
        assert any(
            r.levelname == "ERROR" and "HTTP 401" in r.getMessage() for r in caplog.records
        )

    def test_correlation_forwards_auth(self, client):
        with patch("app.api.assessments.OrionClient") as mock_cls, \
                patch("httpx.AsyncClient") as mock_http:
            inst = AsyncMock()
            inst.query_entities = AsyncMock(return_value=[])
            inst.close = AsyncMock()
            mock_cls.return_value = inst
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value={"data": []})
            get = AsyncMock(return_value=mock_resp)
            mock_http.return_value.__aenter__.return_value.get = get
            resp = client.get(
                "/api/crop-health/assessments/correlation?parcelId=parcel-a",
                headers={"Authorization": "Bearer tok", "X-Auth-Signature": "sig:1"},
            )
        assert resp.status_code == 200
        headers = get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer tok"
        assert headers["X-Tenant-ID"] == "test-tenant"
        assert headers["X-Auth-Signature"] == "sig:1"


def test_mapper_reads_soil_suitability_roundtrip():
    from datetime import datetime, timezone
    from app.schemas import CropHealthAssessment, SoilSuitability
    from app.api.assessment_mapper import map_entity_to_assessment
    entity = CropHealthAssessment(
        parcel_id="urn:ngsi-ld:AgriParcel:t:1",
        assessed_at=datetime(2026, 6, 21, tzinfo=timezone.utc),
        soil_suitability=SoilSuitability(verdict="marginal", reason="pH 7.4",
            confidence="medium")).to_ngsi_ld()
    entity["id"] = "urn:ngsi-ld:CropHealthAssessment:t:1"
    out = map_entity_to_assessment(entity)
    assert out["soilSuitability"]["verdict"] == "marginal"
    assert out["soilSuitability"]["confidence"] == "medium"


def test_mapper_soil_suitability_absent():
    from app.api.assessment_mapper import map_entity_to_assessment
    out = map_entity_to_assessment({"id": "urn:x", "type": "CropHealthAssessment"})
    assert out.get("soilSuitability") is None


def test_pipeline_surfaces_soil_suitability_from_context():
    from datetime import datetime, timezone
    from app.schemas import CropHealthAssessment, SoilSuitability
    from app.services.pipeline import attach_soil_suitability

    class _Ctx:  # minimal stand-in for CropContext with a populated soil.suitability
        class soil:
            suitability = SoilSuitability(verdict="marginal", reason="pH 7.4 above max")
    a = CropHealthAssessment(parcel_id="urn:p:1", assessed_at=datetime(2026, 6, 21, tzinfo=timezone.utc))
    attach_soil_suitability(a, _Ctx())
    assert a.soil_suitability.verdict == "marginal"


def test_pipeline_soil_suitability_none_when_no_context():
    from datetime import datetime, timezone
    from app.schemas import CropHealthAssessment
    from app.services.pipeline import attach_soil_suitability
    a = CropHealthAssessment(parcel_id="urn:p:1", assessed_at=datetime(2026, 6, 21, tzinfo=timezone.utc))
    attach_soil_suitability(a, None)
    assert a.soil_suitability is None
