"""Yield Gap Engine — Doorenbos-Kassam (FAO-33) yield response to water.

Estimates the percentage of yield potential achieved based on actual
evapotranspiration vs maximum evapotranspiration per phenological stage.

IMPORTANT: This is NOT a yield prediction. It is a "yield potential
utilization" indicator. Always exposed as percentage with breakdown by stage.
Never exposed as absolute yield (tons/ha).

Formula: Ya/Ymax = Π [1 - Ky_i × (1 - ETa_i/ETm_i)]
         where i = phenological stage
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StageYieldLoss:
    stage: str
    ky: float
    eta_ratio: float          # ETa / ETm (0-1)
    loss_pct: float            # percentage points lost in this stage
    method: str                # derived_from_CWSI | derived_from_water_balance | measured


@dataclass
class YieldGapResult:
    yield_utilization_pct: float = 100.0  # % of Ymax achieved
    stage_losses: list[StageYieldLoss] = field(default_factory=list)
    dominant_loss_stage: str = ""
    confidence: str = "medium"            # high | medium | low
    data_fidelity: str = "regional_proxy"


def evaluate_yield_gap(
    cwsi_by_stage: dict[str, float],
    ky_by_stage: dict[str, float],
    method: str = "derived_from_CWSI",
    fidelity: str = "regional_proxy",
) -> YieldGapResult:
    """Calculate yield gap per Doorenbos-Kassam FAO-33.

    ETa/ETm is derived from CWSI: ETa/ETm ≈ 1 - CWSI (Jackson et al. 1981)

    Args:
        cwsi_by_stage: Dict of stage_name → mean CWSI for that stage
        ky_by_stage: Dict of stage_name → Ky coefficient (from BioOrchestrator)
        method: How ETa was derived (derived_from_CWSI, derived_from_water_balance, measured)
        fidelity: dataFidelity level

    Returns:
        YieldGapResult with utilization % and stage-by-stage breakdown
    """
    result = YieldGapResult(data_fidelity=fidelity)

    if not cwsi_by_stage or not ky_by_stage:
        result.confidence = "low"
        result.yield_utilization_pct = 100.0
        return result

    utilization = 1.0
    stages = sorted(set(list(cwsi_by_stage.keys()) + list(ky_by_stage.keys())))

    for stage in stages:
        cwsi = cwsi_by_stage.get(stage, 0.0)
        ky = ky_by_stage.get(stage, 0.45)

        # Derive ETa/ETm from CWSI: 1 - CWSI
        eta_ratio = max(0.1, 1.0 - cwsi)

        # Doorenbos-Kassam: [1 - Ky × (1 - ETa/ETm)]
        stage_factor = 1.0 - ky * (1.0 - eta_ratio)

        # Cap at reasonable bounds
        stage_factor = max(0.1, min(1.0, stage_factor))
        utilization *= stage_factor

        loss_pct = round((1.0 - stage_factor) * 100, 1)
        if loss_pct > 1:
            result.stage_losses.append(StageYieldLoss(
                stage=stage, ky=ky, eta_ratio=round(eta_ratio, 2),
                loss_pct=loss_pct, method=method,
            ))

    result.yield_utilization_pct = round(utilization * 100, 1)

    if result.stage_losses:
        result.dominant_loss_stage = max(result.stage_losses, key=lambda s: s.loss_pct).stage

    # Confidence based on fidelity
    fid_conf = {"onsite_calibrated": "high", "onsite_uncalibrated": "high",
                "local_proxy": "medium", "regional_proxy": "medium",
                "modeled_opendata": "low"}
    result.confidence = fid_conf.get(fidelity, "medium")

    return result
