from datetime import datetime, timezone

import pytest

from app.services.terrain_meteo import apply_terrain_meteo, cross_daily, overlap_fractions
from app.services.zonation import Zone

# ~100 m x 100 m square near 42 N (1e-3 deg lat ~ 111 m)
LAT0, LON0 = 42.0, -1.6
DLAT = 100 / 111320
DLON = 100 / (111320 * 0.7431)  # cos(42 deg)


def _rect(x0, y0, x1, y1):
    """Fractions of the unit square -> Polygon ring."""
    lo = lambda x: LON0 + x * DLON  # noqa: E731
    la = lambda y: LAT0 + y * DLAT  # noqa: E731
    return [[lo(x0), la(y0)], [lo(x0), la(y1)], [lo(x1), la(y1)], [lo(x1), la(y0)], [lo(x0), la(y0)]]


def _poly(*rings):
    return {"type": "Polygon", "coordinates": list(rings)}


ZONE_SQ = _poly(_rect(0, 0, 1, 1))


def _unit(zid, geom, **kw):
    return Zone(zone_id=zid, geometry=geom, **kw)


A = _unit("A", _poly(_rect(0, 0, 0.5, 1)))      # west half
B = _unit("B", _poly(_rect(0.5, 0, 0.75, 1)))   # next quarter


def test_fractions_normalised_over_covered_part():
    fr, covered, ha = overlap_fractions(ZONE_SQ, [A, B], step_m=2.0)
    assert covered == pytest.approx(0.75, abs=0.03)
    assert fr["A"] == pytest.approx(2 / 3, abs=0.03) and fr["B"] == pytest.approx(1 / 3, abs=0.03)
    assert sum(fr.values()) == pytest.approx(1.0)
    assert ha["A"] == pytest.approx(0.5, abs=0.03)


def test_unit_only_inside_hole_has_zero_share():
    zone = _poly(_rect(0, 0, 1, 1), _rect(0.25, 0.25, 0.75, 0.75))  # hole in the middle
    inner = _unit("in", _poly(_rect(0.3, 0.3, 0.7, 0.7)))
    outer = _unit("out", _poly(_rect(0, 0, 1, 0.2)))
    fr, covered, ha = overlap_fractions(zone, [inner, outer], step_m=2.0)
    assert fr.get("in", 0.0) == 0.0 and ha.get("in", 0.0) == 0.0
    assert fr["out"] == pytest.approx(1.0)
    assert covered == pytest.approx(0.2 / 0.75, abs=0.03)


def test_overlap_fractions_empty():
    assert overlap_fractions(ZONE_SQ, []) == ({}, 0.0, {})


def _u(zid, **kw):
    return _unit(zid, ZONE_SQ, **kw)


def test_cross_meteo_weighted_mean_and_coldest():
    a = _u("A", t_min=2.0, t_max=14.0, eto=1.0)
    b = _u("B", t_min=-1.5, t_max=12.0, eto=0.8)
    z = _u("L")
    apply_terrain_meteo(z, [a, b], {"A": .85, "B": .15}, 1.0, {"A": .85, "B": .15})
    assert z.t_min == pytest.approx(1.475) and z.eto == pytest.approx(0.97)
    assert z.t_max == pytest.approx(13.7)
    assert z.t_min_coldest == -1.5


def test_coldest_ignores_tiny_unit():
    a = _u("A", t_min=2.0)
    b = _u("B", t_min=-3.0)
    z = _u("L")
    apply_terrain_meteo(z, [a, b], {"A": .95, "B": .05}, 1.0, {"A": 0.95, "B": 0.02})
    assert z.t_min_coldest == 2.0


def test_coldest_falls_back_to_largest_share():
    a = _u("A", t_min=2.0)
    z = _u("L")
    apply_terrain_meteo(z, [a], {"A": 0.05}, 1.0, {"A": 0.01})
    assert z.t_min_coldest == 2.0


def test_cross_meteo_skips_low_coverage():
    a = _u("A", t_min=2.0, t_max=10.0, eto=1.0)
    z = _u("L")
    apply_terrain_meteo(z, [a], {"A": 1.0}, 0.4, {"A": 1.0})
    assert z.t_min is None and z.t_min_coldest is None and z.eto is None and z.observed_at is None


def test_missing_variable_renormalised_and_oldest_observed():
    old = datetime(2026, 11, 1, tzinfo=timezone.utc)
    new = datetime(2026, 11, 2, tzinfo=timezone.utc)
    a = _u("A", t_min=2.0, eto=1.0, observed_at=new)
    b = _u("B", t_min=4.0, eto=None, observed_at=old)
    z = _u("L")
    apply_terrain_meteo(z, [a, b], {"A": .5, "B": .5}, 1.0, {"A": 1.0, "B": 1.0})
    assert z.t_min == pytest.approx(3.0) and z.eto == pytest.approx(1.0)
    assert z.t_max is None and z.solar_radiation_wm2 is None
    assert z.observed_at == old


def test_cross_daily_renormalises_missing_unit_day():
    daily = {
        "A": [{"date": "2026-11-02", "tMin": 2.0, "tMax": 10.0, "eto": 1.0},
              {"date": "2026-11-01", "tMin": 0.0, "tMax": 8.0, "eto": 0.5}],
        "B": [{"date": "2026-11-01", "tMin": 4.0, "tMax": 12.0, "eto": 1.5}],
    }
    rows = cross_daily(daily, {"A": 0.75, "B": 0.25})
    assert [r["date"] for r in rows] == ["2026-11-01", "2026-11-02"]
    assert rows[0]["tMin"] == pytest.approx(1.0) and rows[0]["eto"] == pytest.approx(0.75)
    assert rows[1]["tMin"] == 2.0 and rows[1]["tMax"] == 10.0


def _square_m(side_m):
    return _poly(_rect(0, 0, side_m / 100, side_m / 100))


def test_overlap_ha_matches_real_area_on_small_zone():
    zone = _square_m(14)
    unit = _unit("U", _square_m(30))
    fr, covered, ha = overlap_fractions(zone, [unit])
    assert covered == pytest.approx(1.0) and fr["U"] == pytest.approx(1.0)
    assert ha["U"] == pytest.approx(0.0196, rel=0.05)


def test_default_step_on_quarter_hectare_zone():
    zone = _square_m(50)
    west = _unit("W", _poly(_rect(0, 0, 0.185, 0.6)))
    fr, covered, ha = overlap_fractions(zone, [west])  # default step_m
    assert covered == pytest.approx(0.37, abs=0.02)
    assert ha["W"] == pytest.approx(0.37 * 0.25, rel=0.06)


def test_thin_zone_not_missed_at_default_step():
    thin = _poly(_rect(0, 0, 1, 0.06))  # 6 m wide strip
    unit = _unit("U", _poly(_rect(0, 0, 1, 1)))
    fr, covered, ha = overlap_fractions(thin, [unit])
    assert covered == pytest.approx(1.0) and ha["U"] == pytest.approx(0.06, rel=0.1)


def test_coldest_fallback_tie_broken_by_zone_id():
    z = _u("L")
    apply_terrain_meteo(z, [_u("B", t_min=1.0), _u("A", t_min=5.0)], {"A": 0.05, "B": 0.05}, 1.0, {"A": 0.0, "B": 0.0})
    assert z.t_min_coldest == 5.0  # A wins the tie


def test_cross_daily_ignores_non_numeric_values():
    rows = {"a": [{"date": "2026-05-01", "tMin": "n/a", "tMax": 20.0, "eto": 2.0}],
            "b": [{"date": "2026-05-01", "tMin": 4.0, "tMax": 22.0, "eto": 2.0}]}
    out = cross_daily(rows, {"a": 0.5, "b": 0.5})
    assert out == [{"date": "2026-05-01", "tMin": 4.0, "tMax": 21.0, "eto": 2.0}]


# --- F1: bounded cost, cache, bounding-box prefilter -------------------------------------

def _blob(n, r=0.5):
    import math
    ring = [[LON0 + (0.5 + r * (1 + 0.1 * math.sin(7 * 2 * math.pi * k / n)) * math.cos(2 * math.pi * k / n)) * DLON,
             LAT0 + (0.5 + r * (1 + 0.1 * math.sin(7 * 2 * math.pi * k / n)) * math.sin(2 * math.pi * k / n)) * DLAT]
            for k in range(n)]
    return _poly(ring + [ring[0]])


@pytest.fixture
def pip_counter(monkeypatch):
    from app.services import terrain_meteo as tm
    tm._CACHE.clear()
    calls = {"n": 0}
    real = tm.point_in_polygon

    def counting(lon, lat, geom):
        calls["n"] += 1
        return real(lon, lat, geom)

    monkeypatch.setattr(tm, "point_in_polygon", counting)
    yield calls
    tm._CACHE.clear()


def test_large_zone_pip_calls_are_capped(pip_counter):
    from app.services.terrain_meteo import _MAX_SAMPLES
    zone = _poly(_rect(0, 0, 1, 1))
    units = [_unit(f"u{i}", _poly(_rect(i / 12, 0, (i + 1) / 12, 1))) for i in range(12)]
    big = _poly(_rect(0, 0, 100, 100))  # ~1 km x ... bbox far larger than any parcel: still capped
    overlap_fractions(big, units, step_m=1.0)
    # zone test per sample + at most one hit per sample among the units
    assert pip_counter["n"] <= _MAX_SAMPLES * (1 + len(units))
    assert _MAX_SAMPLES <= 2_500


def test_bbox_prefilter_skips_disjoint_units(pip_counter):
    zone = _poly(_rect(0, 0, 1, 1))
    far = [_unit(f"far{i}", _poly(_rect(5 + i, 5, 6 + i, 6))) for i in range(10)]
    near = _unit("near", _poly(_rect(0, 0, 1, 1)))
    fr, covered, _ = overlap_fractions(zone, far + [near], step_m=2.0)
    assert fr == {"near": pytest.approx(1.0)} and covered == pytest.approx(1.0)
    # far units never reach point_in_polygon: calls = zone + near per inside sample only
    assert pip_counter["n"] <= 2 * 2_500


def test_second_identical_call_hits_cache(pip_counter):
    zone = _blob(300)
    units = [_unit("A", _blob(120, 0.3)), _unit("B", _blob(120, 0.45))]
    first = overlap_fractions(zone, units)
    n = pip_counter["n"]
    assert n > 0
    second = overlap_fractions(zone, list(reversed(units)))  # order-insensitive
    assert pip_counter["n"] == n
    assert second == first
    second[0]["A"] = 99.0  # callers cannot corrupt the cache
    assert overlap_fractions(zone, units)[0]["A"] != 99.0


def test_cache_invalidated_when_unit_geometry_changes(pip_counter):
    zone = _poly(_rect(0, 0, 1, 1))
    overlap_fractions(zone, [_unit("A", _poly(_rect(0, 0, 0.5, 1)))], step_m=2.0)
    n = pip_counter["n"]
    fr, _, _ = overlap_fractions(zone, [_unit("A", _poly(_rect(0, 0, 0.25, 1)))], step_m=2.0)
    assert pip_counter["n"] > n


def test_large_vertex_zone_completes_with_correct_split(pip_counter):
    zone = _blob(1000)
    units = [_unit("W", _poly(_rect(-1, -1, 0.5, 2))), _unit("E", _poly(_rect(0.5, -1, 2, 2)))]
    fr, covered, _ = overlap_fractions(zone, units)
    assert covered == pytest.approx(1.0)
    assert fr["W"] == pytest.approx(0.5, abs=0.06)


def test_multipolygon_zone_counts_both_parts():
    """Production 'high' zones are MultiPolygons."""
    from app.services import terrain_meteo as tm
    tm._CACHE.clear()
    zone = {"type": "MultiPolygon",
            "coordinates": [[_rect(0, 0, 0.3, 1)], [_rect(0.7, 0, 1, 1)]]}
    west = _unit("W", _poly(_rect(0, 0, 0.5, 1)))
    east = _unit("E", _poly(_rect(0.5, 0, 1, 1)))
    fr, covered, ha = overlap_fractions(zone, [west, east], step_m=2.0)
    assert covered == pytest.approx(1.0)
    assert fr["W"] == pytest.approx(0.5, abs=0.03) and fr["E"] == pytest.approx(0.5, abs=0.03)
    assert ha["W"] + ha["E"] == pytest.approx(0.6 * 1.0 * 100 * 100 / 10_000, rel=0.08)  # 0.6 of 1 ha
