"""Composite Stress Engine — weighted by phenological sensitivity (Ky FAO-33).

Combines water (CWSI, MDS, Water Balance), thermal, and vigor into a single
interpretable stress index. Weights are derived from Ky coefficients per
phenological stage — flowering is weighted more heavily than vegetative growth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Ky coefficients per phenological stage (FAO-33, Doorenbos-Kassam 1979)
# Higher Ky = more sensitive to water stress in that stage
DEFAULT_KY: dict[str, float] = {
    "vegetative": 0.45,
    "stem_elongation": 0.60,
    "flowering": 1.15,
    "fruit_set": 1.00,
    "pit_hardening": 0.85,
    "kernel_fill": 0.85,
    "fruit_growth": 0.70,
    "veraison": 0.85,
    "ripening": 0.50,
    "senescence": 0.30,
}


@dataclass
class CompositeStressResult:
    composite_index: float = 0.0       # 0-100, higher = more stress
    dominant_stressor: str = "none"    # water | thermal | vigor | none
    water_contribution: float = 0.0
    thermal_contribution: float = 0.0
    vigor_contribution: float = 0.0
    stage_ky: float = 0.45
    condition: str = "no_stress"       # no_stress | mild | moderate | severe
    data_fidelity: str = "regional_proxy"


def evaluate_composite_stress(
    cwsi: float | None = None,
    mds_ratio: float | None = None,
    water_balance_mm: float | None = None,
    thermal_severity: str | None = None,
    vigor_index: float | None = None,
    stage: str = "vegetative",
    ky_override: dict[str, float] | None = None,
    fidelity: str = "regional_proxy",
) -> CompositeStressResult:
    """Combine all stress indicators weighted by phenological sensitivity.

    Args:
        cwsi: Crop Water Stress Index (0-1)
        mds_ratio: MDS / MDS_ref ratio
        water_balance_mm: Water balance in mm (negative = deficit)
        thermal_severity: LOW | MEDIUM | HIGH | CRITICAL from thermal engine
        vigor_index: Crop vigor index (0-1, lower = worse)
        stage: Current phenological stage name
        ky_override: Optional per-stage Ky overrides from BioOrchestrator
        fidelity: dataFidelity level

    Returns:
        CompositeStressResult with weighted index and breakdown
    """
    ky_map = ky_override or DEFAULT_KY
    ky = ky_map.get(stage, 0.45)
    result = CompositeStressResult(stage_ky=ky, data_fidelity=fidelity)

    water_score = 0.0
    thermal_score = 0.0
    vigor_score = 0.0
    count = 0

    # Water stress: combine CWSI + MDS + water balance
    if cwsi is not None:
        # Satellite CWSI gets 0.7× weight vs IoT (1.0×) — lower confidence
        try:
            from nkz_platform_sdk.constants import SensorFidelity
            cwsi_weight = 0.7 if fidelity == SensorFidelity.MODELED_OPENDATA else 1.0
        except ImportError:
            cwsi_weight = 0.7 if fidelity == "modeled_opendata" else 1.0
        water_score += cwsi * 100 * cwsi_weight  # 0-100 scale
        count += 1
    if mds_ratio is not None:
        # MDS ratio: 1.0 = normal, >1.3 = stress
        mds_pct = min(100, max(0, (mds_ratio - 0.8) / 1.2 * 100))
        water_score += mds_pct
        count += 1
    if water_balance_mm is not None:
        # Deficit: -15mm = 100 stress, +5mm = 0 stress
        balance_stress = max(0, min(100, (-water_balance_mm + 5) / 20 * 100))
        water_score += balance_stress
        count += 1

    if count > 0:
        water_score /= count

    # Thermal stress: map severity to 0-100
    severity_map = {"LOW": 15, "MEDIUM": 40, "HIGH": 70, "CRITICAL": 95}
    if thermal_severity:
        thermal_score = severity_map.get(thermal_severity, 0)

    # Vigor: invert so lower vigor = higher stress
    if vigor_index is not None:
        vigor_score = max(0, (1.0 - vigor_index) * 100)

    # Weighted combination (Ky amplifies water stress in sensitive stages)
    result.water_contribution = water_score * ky
    result.thermal_contribution = thermal_score * 0.5
    result.vigor_contribution = vigor_score * 0.3

    total = result.water_contribution + result.thermal_contribution + result.vigor_contribution
    result.composite_index = min(100, round(total, 1))

    # Dominant stressor
    contributions = {
        "water": result.water_contribution,
        "thermal": result.thermal_contribution,
        "vigor": result.vigor_contribution,
    }
    if max(contributions.values()) > 5:
        result.dominant_stressor = max(contributions, key=contributions.get)

    # Condition
    if result.composite_index < 25:
        result.condition = "no_stress"
    elif result.composite_index < 50:
        result.condition = "mild"
    elif result.composite_index < 75:
        result.condition = "moderate"
    else:
        result.condition = "severe"

    return result
