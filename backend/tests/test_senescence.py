"""NDVI end-of-season rule (TIMESAT amplitude rule on a Savitzky-Golay smoothed series)."""
from __future__ import annotations

import math
from datetime import date, timedelta

from app.engines import senescence
from app.engines.senescence import end_of_season_reached

START = date(2026, 3, 1)


def _series(values, step=10):
    return [(START + timedelta(days=i * step), v) for i, v in enumerate(values)]


# Synthetic crop season: rise to a 0.85 peak, then fall.
RISE = [0.20, 0.30, 0.50, 0.70, 0.85, 0.86, 0.85]
DROP = [0.70, 0.45, 0.25, 0.20]
STILL_GREEN = [0.85, 0.84, 0.82, 0.80]


def test_end_of_season_detected_after_drop():
    assert end_of_season_reached(_series(RISE + DROP), 0.2) is True


def test_still_green_after_peak_is_false():
    assert end_of_season_reached(_series(RISE + STILL_GREEN), 0.2) is False


def test_peak_at_the_end_is_false():
    rising = [0.20, 0.25, 0.30, 0.40, 0.50, 0.65, 0.78, 0.85, 0.88]
    assert end_of_season_reached(_series(rising), 0.2) is False


def test_insufficient_points_none():
    assert end_of_season_reached(_series([0.2, 0.8, 0.3]), 0.2) is None
    assert end_of_season_reached([], 0.2) is None
    assert senescence.MIN_OBSERVATIONS >= 3


def test_non_finite_dropped():
    # Garbage points are dropped, not smoothed in: with them removed the series is too short.
    short = _series([0.2, 0.5, 0.8, 0.5, 0.2, 0.2, 0.2])
    bad = [(START + timedelta(days=200), math.nan), (START + timedelta(days=210), math.inf),
           (START + timedelta(days=220), 1.7), (START + timedelta(days=230), -3.0)]
    n_ok = len(short)
    if n_ok >= senescence.MIN_OBSERVATIONS:  # keep the test honest if the constant changes
        short = short[: senescence.MIN_OBSERVATIONS - 1]
    assert end_of_season_reached(short + bad, 0.2) is None
    # and valid series with garbage mixed in gives the same answer as without
    good = _series(RISE + DROP)
    assert end_of_season_reached(good + bad, 0.2) is True


def test_unsorted_and_duplicate_dates():
    pts = _series(RISE + DROP)
    shuffled = list(reversed(pts)) + [pts[2]]
    assert end_of_season_reached(shuffled, 0.2) is True


def test_flat_series_has_no_season():
    assert end_of_season_reached(_series([0.5] * 14), 0.2) is None


def test_series_starting_after_peak_has_no_base():
    assert end_of_season_reached(_series([0.9, 0.7, 0.5, 0.3, 0.2, 0.2, 0.2, 0.2, 0.2]), 0.2) is None


def test_last_point_outlier_is_not_the_end():
    # One very low last acquisition (cloud/shadow) after a green plateau.
    assert end_of_season_reached(_series(RISE + STILL_GREEN + [0.15]), 0.2) is not True


def test_dip_then_recover_is_false():
    # A two-observation cloudy dip at 10-day spacing that recovers.
    dip = RISE + [0.80, 0.30, 0.25, 0.80, 0.84, 0.85]
    assert end_of_season_reached(_series(dip), 0.2) is False


def test_sustained_decline_is_true():
    assert end_of_season_reached(_series(RISE + [0.60, 0.35, 0.22, 0.20, 0.19]), 0.2) is True


def test_duplicate_dates_keep_the_highest_ndvi():
    pts = _series(RISE + DROP)
    cloudy = [(d, 0.0) for d, _ in pts]  # contaminated duplicates must not win
    assert end_of_season_reached(pts + cloudy, 0.2) is True
    # two-peak seasons are read from the highest peak (documented limit, not tested further)
