"""End of season from a satellite NDVI series (TIMESAT amplitude rule).

Rule (Joensson & Eklundh, TIMESAT 2.3 Users Guide; method paper
doi:10.1016/j.cageo.2004.05.006): the season ends at the first date after the peak
where the smoothed series has fallen to ``base + X * amplitude``, with amplitude =
peak - base and X = ``end_fraction`` (the caller passes the published value).
TIMESAT smooths with Savitzky-Golay among other fits; its guide gives no window,
order, step or minimum count, so those below are assumptions.

Pure Python on purpose: numpy/scipy are not runtime dependencies of this module.
"""

from __future__ import annotations

import math
from datetime import date

# ASSUMPTION: the series is resampled to a 5-day grid (Sentinel-2 revisit); TIMESAT
# fits regularly sampled data and its guide states no step.
GRID_STEP_DAYS = 5
# ASSUMPTION: Savitzky-Golay window of 7 grid points (35 days), polynomial order 2;
# not stated in the TIMESAT guide.
SG_WINDOW = 7
SG_ORDER = 2
# ASSUMPTION: at least 8 usable observations; no source gives a minimum count.
# Fewer means "insufficient data", so post-maturity is never declared on a thin series.
MIN_OBSERVATIONS = 8
# ASSUMPTION: a seasonal amplitude below 0.2 NDVI is not a crop season (bare soil or
# noise); TIMESAT has an amplitude cut-off but gives no value.
MIN_AMPLITUDE = 0.2


def _clean(points: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """Finite NDVI within [-1, 1], one value per date (last wins), sorted by date."""
    by_day: dict[date, float] = {}
    for d, v in points:
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and -1.0 <= x <= 1.0:
            by_day[d] = x
    return sorted(by_day.items())


def _resample(points: list[tuple[date, float]]) -> list[float]:
    """Linear interpolation of the observations onto a regular grid."""
    first = points[0][0]
    span = (points[-1][0] - first).days
    out: list[float] = []
    j = 0
    for t in range(0, span + 1, GRID_STEP_DAYS):
        while j < len(points) - 2 and (points[j + 1][0] - first).days < t:
            j += 1
        (d0, v0), (d1, v1) = points[j], points[j + 1]
        t0, t1 = (d0 - first).days, (d1 - first).days
        w = 0.0 if t1 == t0 else min(max((t - t0) / (t1 - t0), 0.0), 1.0)
        out.append(v0 + (v1 - v0) * w)
    return out


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (small dense system)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][k] * x[k] for k in range(r + 1, n))) / m[r][r]
    return x


def _savgol(y: list[float], window: int, order: int) -> list[float]:
    """Savitzky-Golay smoothing: local least-squares polynomial; edges use the nearest full window."""
    n, half = len(y), window // 2
    out: list[float] = []
    for i in range(n):
        s = min(max(i - half, 0), n - window)
        xs = [k - i for k in range(s, s + window)]  # centred on the point being smoothed
        ys = y[s:s + window]
        a = [[sum(x ** (r + c) for x in xs) for c in range(order + 1)] for r in range(order + 1)]
        b = [sum(yv * x ** r for x, yv in zip(xs, ys)) for r in range(order + 1)]
        out.append(_solve(a, b)[0])  # polynomial value at x = 0
    return out


def end_of_season_reached(points: list[tuple[date, float]], end_fraction: float) -> bool | None:
    """True when the smoothed NDVI has fallen to base + end_fraction * amplitude after the peak.

    None = cannot tell (too few observations, no usable season, or no data before the
    peak to define the base). False = a season is visible and has not ended.
    """
    if not (0.0 < end_fraction < 1.0):
        return None
    pts = _clean(points)
    if len(pts) < MIN_OBSERVATIONS:
        return None
    grid = _resample(pts)
    if len(grid) < SG_WINDOW:
        return None
    sm = _savgol(grid, SG_WINDOW, SG_ORDER)
    peak = max(range(len(sm)), key=lambda i: sm[i])
    if peak == 0:
        return None  # series starts at/after the peak: no base level
    base = min(sm[: peak + 1])
    amplitude = sm[peak] - base
    if amplitude < MIN_AMPLITUDE:
        return None
    threshold = base + end_fraction * amplitude
    return any(v <= threshold for v in sm[peak + 1:])
