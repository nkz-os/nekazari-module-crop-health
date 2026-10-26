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


def test_explicit_zone_type_wins_over_heuristics():
    rows = [{"id": "a", "location": POLY, "nkz:zoneId": "a", "nkz:zoneType": "management"},
            {"id": "b", "location": POLY, "nkz:zoneId": "b", "nkz:centroid": [0, 0]}]
    assert [r["id"] for r in select_management_zones(rows)] == ["a"]


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
