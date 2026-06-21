from app.services.zonation import (
    point_in_polygon,
    sensors_in_zone,
    consolidate_sensor_readings,
    Zone,
)

_SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]}


def test_point_in_polygon():
    assert point_in_polygon(5, 5, _SQUARE) is True
    assert point_in_polygon(20, 20, _SQUARE) is False


def test_point_in_polygon_multipolygon():
    mp = {"type": "MultiPolygon", "coordinates": [_SQUARE["coordinates"]]}
    assert point_in_polygon(5, 5, mp) is True
    assert point_in_polygon(20, 20, mp) is False


def test_consolidate_means_per_metric():
    # Two sensors in the same zone — must average, not last-write-wins.
    out = consolidate_sensor_readings([
        {"soil_moisture": 20.0, "air_temp_c": 18.0},
        {"soil_moisture": 30.0, "air_temp_c": 22.0},
    ])
    assert out["soil_moisture"] == 25.0
    assert out["air_temp_c"] == 20.0


def test_consolidate_ignores_non_metric_and_non_numeric():
    out = consolidate_sensor_readings([
        {"id": "s1", "lon": 1.0, "lat": 2.0, "dateObserved": "x", "soil_moisture": 10.0, "flag": "ok"},
    ])
    assert out == {"soil_moisture": 10.0}


def test_consolidate_empty():
    assert consolidate_sensor_readings([]) == {}


def test_sensors_in_zone_filters_by_polygon():
    z = Zone(zone_id="z0", geometry=_SQUARE)
    s_in = {"lon": 5, "lat": 5, "soil_moisture": 10}
    s_out = {"lon": 50, "lat": 50, "soil_moisture": 99}
    assert sensors_in_zone(z, [s_in, s_out]) == [s_in]


def test_sensors_without_coords_unassignable():
    z = Zone(zone_id="z0", geometry=_SQUARE)
    assert sensors_in_zone(z, [{"soil_moisture": 1}]) == []
