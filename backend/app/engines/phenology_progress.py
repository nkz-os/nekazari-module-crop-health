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

    # Check if GDD suggests a different stage than what's declared
    for stage_name, (gdd_min, gdd_max) in stage_gdd_thresholds.items():
        if gdd_min <= gdd_accumulated < gdd_max and stage_name != current_stage:
            if stage_name > current_stage:
                result.deviation = "behind"  # GDD says ahead but stage says behind
            else:
                result.deviation = "ahead"
            return result

    return result
