from app.services.zonation import is_management_zone, select_management_zones

POLY = {"type": "Polygon", "coordinates": [[[-2, 42], [-2, 42.1], [-1.9, 42.1], [-2, 42]]]}
MULTI_BIG = {"type": "MultiPolygon", "coordinates": [POLY["coordinates"]] * 300}


def _multi(n):
    return {"type": "MultiPolygon", "coordinates": [POLY["coordinates"]] * n}


def test_weather_map_zone_is_management():
    assert is_management_zone({"id": "z1", "location": POLY, "nkz:zoneId": "a", "nkz:centroid": [-1.95, 42.05]})


def test_hydrology_twi_class_is_not_management():
    assert not is_management_zone({"id": "z2", "location": MULTI_BIG, "nkz:zoneId": "twi-high", "nkz:twiMean": 8.1})


def test_manual_zone_without_geometry_is_not_management():
    assert not is_management_zone({"id": "z3", "name": "Cuadrante NO"})


def test_zone_type_is_judged_per_row_not_per_batch():
    rows = [{"id": "a", "location": POLY, "nkz:zoneId": "a", "nkz:zoneType": "hydrology"},
            {"id": "b", "location": POLY, "nkz:zoneId": "b", "nkz:centroid": [0, 0]},
            {"id": "c", "location": POLY, "nkz:zoneId": "c", "nkz:zoneType": "management"}]
    assert [r["id"] for r in select_management_zones(rows)] == ["b", "c"]


def test_empty_multipolygon_is_not_management():
    assert not is_management_zone({"id": "e", "location": _multi(0), "nkz:zoneType": "management"})


def test_multipolygon_part_limit_is_five():
    assert is_management_zone({"id": "m5", "location": _multi(5), "nkz:zoneType": "management"})
    assert not is_management_zone({"id": "m6", "location": _multi(6), "nkz:zoneType": "management"})


def test_other_zone_type_rejected():
    assert not is_management_zone({"id": "t", "location": POLY, "nkz:zoneType": "twi", "nkz:centroid": [0, 0]})


def test_geoproperty_wrapper_is_unwrapped():
    row = {"id": "g", "location": {"type": "GeoProperty", "value": POLY}, "zoneType": "management"}
    assert is_management_zone(row)


def test_no_centroid_or_sector_is_not_management():
    assert not is_management_zone({"id": "n", "location": POLY})


def test_aspect_sector_heuristic():
    assert is_management_zone({"id": "s", "location": POLY, "nkz:aspectSector": "N"})


def test_expanded_iri_attributes_are_recognised():
    """Terms outside the platform @context arrive as full IRIs (as in production)."""
    ns = "https://nkz-os.org/ns/"
    weather_map = {"id": "z-iri", "location": POLY, ns + "zoneId": "a", ns + "centroid": [-1.95, 42.05],
                   ns + "aspectSector": "N"}
    hydrology = {"id": "z-twi", "location": POLY, ns + "zoneId": "twi-high", ns + "centroid": [0, 0], ns + "twiMean": 8.1}
    assert is_management_zone(weather_map)
    assert not is_management_zone(hydrology)
    assert [r["id"] for r in select_management_zones([weather_map, hydrology])] == ["z-iri"]
