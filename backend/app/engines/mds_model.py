"""
MDS Engine — Maximum Daily Shrinkage from dendrómetro data.

Implements:
    MDS_t = max(D_tallo, 24h) - min(D_tallo, 24h)

Then compares MDS_t against MDS_ref (theoretical expected value for
the species and phenological stage) to quantify cellular-level
water stress severity.

The raw trunk diameter readings are stored in a Redis sliding window
by the webhook handler; this engine reads them.
"""

from __future__ import annotations

from app.schemas import MDSResult, Severity, TimeseriesPoint


# ── Severity thresholds (ratio = MDS_actual / MDS_ref) ────────────────────────
_SEVERITY_THRESHOLDS: list[tuple[float, Severity]] = [
    (2.0, Severity.CRITICAL),
    (1.5, Severity.HIGH),
    (1.2, Severity.MEDIUM),
    (0.0, Severity.LOW),
]


def mds_severity(mds_actual: float, mds_ref: float) -> Severity:
    """Determine MDS severity from ratio of actual to reference.

    Thresholds:
        ratio < 1.2  → LOW
        1.2 ≤ ratio < 1.5 → MEDIUM
        1.5 ≤ ratio < 2.0 → HIGH
        ratio ≥ 2.0  → CRITICAL

    Args:
        mds_actual: Measured MDS (µm).
        mds_ref: Expected MDS for species/stage (µm).

    Returns:
        Severity enum value.
    """
    if mds_ref <= 0:
        # Cannot compute ratio — treat as unknown → MEDIUM as precaution
        return Severity.MEDIUM

    ratio = mds_actual / mds_ref
    for threshold, severity in _SEVERITY_THRESHOLDS:
        if ratio >= threshold:
            return severity
    return Severity.LOW


def calculate_mds_from_readings(
    readings: list[TimeseriesPoint],
    mds_ref: float,
) -> MDSResult | None:
    """Calculate MDS from a list of trunk diameter readings.

    MDS_t = max(D_tallo) - min(D_tallo) over the provided window.

    Args:
        readings: Trunk diameter readings in µm from the sliding window.
                  Must have at least 2 points.
        mds_ref: Reference MDS for the species/stage (µm).

    Returns:
        MDSResult or None if insufficient data.
    """
    if len(readings) < 2:
        return None

    values = [r.value for r in readings]
    window_max = max(values)
    window_min = min(values)
    mds_um = window_max - window_min

    if mds_um < 0:
        # Should not happen, but guard against data issues
        mds_um = 0.0

    ratio = mds_um / mds_ref if mds_ref > 0 else 0.0
    severity = mds_severity(mds_um, mds_ref)

    return MDSResult(
        mds_um=round(mds_um, 2),
        mds_ref=mds_ref,
        ratio=round(ratio, 3),
        severity=severity,
        window_max=round(window_max, 2),
        window_min=round(window_min, 2),
    )
