"""Sensor readings feed crop-health only when the sensor measures the required medium."""
import pytest

from app.services import observation_medium as om

CTX = "https://nkz-os.org/ns/observationContext"
OVR = "https://nkz-os.org/ns/channelOverrides"


def _dev(medium=None, overrides=None, **extra):
    d = {"id": "urn:ngsi-ld:Device:acme:d1", "type": "Device", **extra}
    if medium is not None:
        d["observationContext"] = {"medium": medium}
    if overrides is not None:
        d["channelOverrides"] = overrides
    return d


@pytest.mark.parametrize("attr,medium", [
    ("airTemperature", "ambientAir"), ("relativeHumidity", "ambientAir"),
    ("photosyntheticPhotonFluxDensity", "ambientAir"), ("solarRadiation", "ambientAir"),
    ("soilMoisture", "soil"),
    ("leafTemperature", "plant"), ("trunkDiameter", "plant"), ("stemDiameter", "plant"),
])
def test_required_medium_accepted(attr, medium):
    assert om.reading_allowed(_dev(medium), attr) is True


@pytest.mark.parametrize("attr,wrong", [
    ("airTemperature", "ambientAirUnderStructure"), ("airTemperature", "enclosedAir"),
    ("airTemperature", "equipment"), ("soilMoisture", "ambientAir"),
    ("leafTemperature", "soil"), ("trunkDiameter", "ambientAir"),
])
def test_other_medium_rejected(attr, wrong):
    assert om.reading_allowed(_dev(wrong), attr) is False


def test_unset_medium_rejected():
    assert om.reading_allowed(_dev(), "airTemperature") is False
    assert om.reading_allowed({"id": "x", "observationContext": {}}, "airTemperature") is False
    assert om.reading_allowed({"id": "x", "observationContext": "junk"}, "airTemperature") is False


def test_normalized_form():
    dev = {"observationContext": {"type": "Property", "value": {"medium": "ambientAir"}},
           "channelOverrides": {"type": "Property", "value": {
               "relativeHumidity": {"observationContext": {"medium": "enclosedAir"}}}}}
    assert om.reading_allowed(dev, "airTemperature") is True
    assert om.reading_allowed(dev, "relativeHumidity") is False


def test_full_iri_keys():
    dev = {CTX: {"medium": "soil"}, OVR: {"airTemperature": {"observationContext": {"medium": "ambientAir"}}}}
    assert om.reading_allowed(dev, "soilMoisture") is True
    assert om.reading_allowed(dev, "airTemperature") is True


def test_override_wins_per_attribute():
    dev = _dev("ambientAir", {"airTemperature": {"observationContext": {"medium": "equipment"}}})
    assert om.reading_allowed(dev, "airTemperature") is False
    assert om.reading_allowed(dev, "relativeHumidity") is True


def test_override_can_grant_on_device_without_medium():
    dev = _dev(None, {"soilMoisture": {"observationContext": {"medium": "soil"}}})
    assert om.reading_allowed(dev, "soilMoisture") is True
    assert om.reading_allowed(dev, "airTemperature") is False


def test_override_without_context_falls_back_to_device():
    dev = _dev("ambientAir", {"airTemperature": {"observesFeature": "x"}})
    assert om.reading_allowed(dev, "airTemperature") is True


def test_untracked_attribute_not_governed():
    assert om.reading_allowed(_dev(), "precipitation") is True


def test_under_structure_air_ok_only_for_park_owned_device():
    park = _dev("ambientAirUnderStructure", controlledAsset="urn:ngsi-ld:AgriSolarPark:acme:p1")
    assert om.reading_allowed(park, "airTemperature") is True
    assert om.reading_allowed(park, "soilMoisture") is False
    parcel_owned = _dev("ambientAirUnderStructure", controlledAsset="urn:ngsi-ld:AgriParcel:acme:f1")
    assert om.reading_allowed(parcel_owned, "airTemperature") is False
    assert om.reading_allowed(_dev("enclosedAir", controlledAsset="urn:ngsi-ld:AgriSolarPark:acme:p1"),
                              "airTemperature") is False


class _Fetch:
    def __init__(self, result):
        self.result, self.calls = result, 0

    async def __call__(self, tenant, device_id):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_gate_allows_and_caches():
    fetch = _Fetch(_dev("ambientAir"))
    gate = om.DeviceMediumGate(fetch, ttl_s=300, clock=lambda: 0.0)
    assert await gate.allows("acme", "d1", "airTemperature") is True
    assert await gate.allows("acme", "d1", "relativeHumidity") is True
    assert fetch.calls == 1


async def test_gate_cache_expires_and_is_tenant_scoped():
    t = [0.0]
    fetch = _Fetch(_dev("ambientAir"))
    gate = om.DeviceMediumGate(fetch, ttl_s=300, clock=lambda: t[0])
    await gate.allows("acme", "d1", "airTemperature")
    await gate.allows("tenant-a", "d1", "airTemperature")
    assert fetch.calls == 2
    t[0] = 301.0
    await gate.allows("acme", "d1", "airTemperature")
    assert fetch.calls == 3


async def test_gate_rejects_and_logs_other_medium(caplog):
    gate = om.DeviceMediumGate(_Fetch(_dev("enclosedAir")), clock=lambda: 0.0)
    with caplog.at_level("DEBUG"):
        assert await gate.allows("acme", "urn:d1", "airTemperature") is False
    line = " ".join(r.getMessage() for r in caplog.records)
    assert "acme" in line and "urn:d1" in line and "airTemperature" in line and "enclosedAir" in line


async def test_gate_broker_failure_skips_with_warning_and_is_not_cached(caplog):
    fetch = _Fetch(RuntimeError("down"))
    gate = om.DeviceMediumGate(fetch, clock=lambda: 0.0)
    with caplog.at_level("WARNING"):
        assert await gate.allows("acme", "d1", "airTemperature") is False
    assert any(r.levelname == "WARNING" for r in caplog.records)
    fetch.result = _dev("ambientAir")
    assert await gate.allows("acme", "d1", "airTemperature") is True


async def test_gate_missing_device_skips():
    gate = om.DeviceMediumGate(_Fetch(None), clock=lambda: 0.0)
    assert await gate.allows("acme", "d1", "airTemperature") is False


async def test_gate_untracked_attribute_needs_no_lookup():
    fetch = _Fetch(None)
    gate = om.DeviceMediumGate(fetch, clock=lambda: 0.0)
    assert await gate.allows("acme", "d1", "precipitation") is True
    assert fetch.calls == 0
