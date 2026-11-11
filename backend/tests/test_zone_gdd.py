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


# --- GDD method parity (shared vectors) ---------------------------------

import json
from pathlib import Path

from app.services.zone_gdd import _daily_gdd

_VECTORS = json.loads((Path(__file__).parent / "data" / "gdd_vectors.json").read_text())["cases"]


@pytest.mark.parametrize("method", ["legacy", "m2", "aquacrop_m3"])
def test_daily_gdd_matches_shared_vectors(method):
    assert len(_VECTORS) >= 30
    for c in _VECTORS:
        got = _daily_gdd({"tMin": c["tmin"], "tMax": c["tmax"]}, c["base"], c["upper"], method)
        assert got == pytest.approx(c[method], abs=1e-9), (method, c)


def test_unknown_method_raises():
    with pytest.raises(ValueError):
        _daily_gdd({"tMin": 1, "tMax": 2}, 0.0, 30.0, "nope")


def test_zone_delta_uses_parcel_method():
    # legacy and aquacrop_m3 differ only when Tmin exceeds the upper cutoff.
    a = [{"date": "2026-07-01", "tMin": 27.0, "tMax": 40.0}]
    b = [{"date": "2026-07-01", "tMin": 10.0, "tMax": 20.0}]
    legacy = zone_gdd_delta({"a": a, "b": b}, W, 0.0, 26.0)
    m3 = zone_gdd_delta({"a": a, "b": b}, W, 0.0, 26.0, gdd_method="aquacrop_m3")
    assert legacy["a"] == pytest.approx((26.5 - 15.0) / 2)
    assert m3["a"] == pytest.approx((26.0 - 15.0) / 2)
    assert legacy["a"] != pytest.approx(m3["a"])


def test_non_cereal_keeps_legacy_bytes():
    daily = {"a": _rows(5, -2, 18), "b": _rows(5, 4, 33)}
    default = zone_gdd_delta(daily, W, 10.0, 30.0)
    explicit = zone_gdd_delta(daily, W, 10.0, 30.0, gdd_method="legacy")
    assert default == explicit
    # the pre-change expression, inlined
    old = {z: [max(0.0, (min(float(r["tMax"]), 30.0) + float(r["tMin"])) / 2.0 - 10.0) for r in rows]
           for z, rows in daily.items()}
    assert default["a"] == pytest.approx(sum(x - (old["a"][i] + old["b"][i]) / 2 for i, x in enumerate(old["a"])), abs=0)


def test_missing_temperature_contributes_nothing():
    for method in ("legacy", "m2", "aquacrop_m3"):
        assert _daily_gdd({"tMin": None, "tMax": 20.0}, 10.0, 30.0, method) is None
        assert _daily_gdd({"tMin": 5.0}, 10.0, 30.0, method) is None
        rows = _rows(2, 8, 22)
        rows[0]["tMin"] = None
        d = zone_gdd_delta({"a": rows, "b": _rows(2, 9, 23)}, W, 10.0, 30.0, gdd_method=method)
        assert set(d) == {"a", "b"}
        # day 1 only present in b -> contributes zero delta; day 2 shared
        g_a = _daily_gdd(_rows(2, 8, 22)[1], 10.0, 30.0, method)
        g_b = _daily_gdd(_rows(2, 9, 23)[1], 10.0, 30.0, method)
        assert d["b"] == pytest.approx((g_b - g_a) / 2)
