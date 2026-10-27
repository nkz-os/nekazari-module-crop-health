import pytest

from app.services.zone_gdd import zone_gdd_delta


def _rows(n, t_min, t_max):
    return [{"date": f"2026-05-{d:02d}", "tMin": t_min, "tMax": t_max} for d in range(1, n + 1)]


W = {"a": 0.5, "b": 0.5}


def test_equal_zones_zero_delta():
    d = zone_gdd_delta({"a": _rows(10, 8, 22), "b": _rows(10, 8, 22)}, W, 10.0, 30.0)
    assert d == {"a": pytest.approx(0.0), "b": pytest.approx(0.0)}


def test_warmer_zone_plus_minus_five():
    d = zone_gdd_delta({"a": _rows(10, 8, 22), "b": _rows(10, 9, 23)}, W, 10.0, 30.0)
    assert d["b"] == pytest.approx(5.0)
    assert d["a"] == pytest.approx(-5.0)


def test_day_present_in_one_zone_gives_zero():
    d = zone_gdd_delta({"a": _rows(3, 8, 22), "b": []}, W, 10.0, 30.0)
    assert d == {"a": pytest.approx(0.0), "b": 0.0}


def test_upper_cutoff_clips():
    d = zone_gdd_delta({"a": _rows(1, 10, 40), "b": _rows(1, 10, 30)}, W, 10.0, 30.0)
    assert d["a"] == pytest.approx(0.0)


def test_missing_temps_ignored():
    rows = _rows(2, 8, 22)
    rows[0]["tMax"] = None
    d = zone_gdd_delta({"a": rows, "b": _rows(2, 9, 23)}, W, 10.0, 30.0)
    assert d["a"] == pytest.approx(-0.5)
    assert d["b"] == pytest.approx(0.5)
