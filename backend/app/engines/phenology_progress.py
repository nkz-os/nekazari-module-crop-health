"""Phenology Progress Engine — GDD accumulation vs expected curve.

Compares actual Growing Degree Days against expected thresholds per
phenological stage to detect advance or delay in crop development.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PhenologyProgressResult:
    gdd_accumulated: float = 0.0
    current_stage: str = ""
    progress_pct: float = 0.0          # % of GDD completed for current stage
    days_to_next_stage: float | None = None  # estimated days remaining
    deviation: str = "on_track"        # ahead | on_track | behind
    data_fidelity: str = "regional_proxy"


def evaluate_phenology_progress(
    gdd_accumulated: float,
    current_stage: str,
    stage_gdd_thresholds: dict[str, tuple[float, float]],
    mean_daily_gdd: float = 8.0,
    fidelity: str = "regional_proxy",
) -> PhenologyProgressResult:
    """Compare actual GDD vs expected thresholds for phenological stage.

    Args:
        gdd_accumulated: Total GDD since season start
        current_stage: Current phenological stage name
        stage_gdd_thresholds: Dict of stage_name → (gdd_min, gdd_max)
                             from BioOrchestrator stage_detection
        mean_daily_gdd: Mean daily GDD for the location (default 8°C for Mediterranean)
        fidelity: dataFidelity level

    Returns:
        PhenologyProgressResult with progress and deviation
    """
    result = PhenologyProgressResult(
        gdd_accumulated=gdd_accumulated,
        current_stage=current_stage,
        data_fidelity=fidelity,
    )

    thresholds = stage_gdd_thresholds.get(current_stage)
    if thresholds:
        gdd_min, gdd_max = thresholds
        stage_gdd_range = gdd_max - gdd_min
        if stage_gdd_range > 0:
            stage_gdd_elapsed = gdd_accumulated - gdd_min
            result.progress_pct = max(0, min(100, (stage_gdd_elapsed / stage_gdd_range) * 100))
            gdd_remaining = gdd_max - gdd_accumulated
            if gdd_remaining > 0 and mean_daily_gdd > 0:
                result.days_to_next_stage = round(gdd_remaining / mean_daily_gdd, 1)

    # Check if GDD suggests a different stage than what's declared (order by gdd_min)
    ordered = sorted(stage_gdd_thresholds.items(), key=lambda kv: kv[1][0])
    names_in_order = [n for n, _ in ordered]
    gdd_stage = derive_stage_from_gdd(gdd_accumulated, stage_gdd_thresholds)
    if gdd_stage != "unknown" and gdd_stage != current_stage and current_stage in names_in_order:
        if names_in_order.index(gdd_stage) > names_in_order.index(current_stage):
            result.deviation = "ahead"   # GDD has advanced beyond the declared stage
        else:
            result.deviation = "behind"
        return result

    return result


def derive_stage_from_gdd(
    gdd: float, thresholds: dict[str, tuple[float, float]]
) -> str:
    """Authoritative current stage from accumulated GDD. Never raises.

    - gdd < first.gdd_min  → first stage
    - gdd >= last.gdd_max   → final stage (held indefinitely past maturity)
    - empty thresholds      → "unknown"
    """
    if not thresholds:
        return "unknown"
    ordered = sorted(thresholds.items(), key=lambda kv: kv[1][0])
    if gdd < ordered[0][1][0]:
        return ordered[0][0]
    for name, (gdd_min, gdd_max) in ordered:
        if gdd_min <= gdd < gdd_max:
            return name
    return ordered[-1][0]
