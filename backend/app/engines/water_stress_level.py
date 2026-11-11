"""One water-stress level for the whole module.

Text, colour, severity and the composite all read the level resolved here, with
the cuts defined once in this file. A missing input is ``no_data``, never
``none``; a stage flagged ``water_sensitive: false`` is ``not_needed``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # schemas imports this module; avoid a runtime cycle
    from app.schemas import CWSIResult, StageWaterFlags, WaterStress, WaterStressReference

# CWSI cuts: level is the highest class whose minimum the value reaches.
# 0.2 = onset of stress in almond (Gonzalez-Dugo et al. 2019,
# doi:10.1016/j.eja.2019.01.010) and olive (Sanchez-Pinero et al. 2022,
# doi:10.1016/j.agwat.2022.107729).
# 0.4 and 0.6: ASSUMPTION: owner-approved 2026-11-03, no published classes
CWSI_CUTS = {"mild": 0.2, "moderate": 0.4, "high": 0.6}

# Cuts on Ks (WaterStress.index = 1 - Ks): none Ks >= 0.95, mild 0.80 <= Ks < 0.95,
# moderate 0.50 <= Ks < 0.80, high Ks < 0.50.
# ASSUMPTION: owner-approved 2026-11-03; FAO-56 only defines Ks < 1 as stress
KS_INDEX_CUTS = {"none_ks_min": 0.95, "mild_ks_min": 0.80, "moderate_ks_min": 0.50}

LEVELS = ("none", "mild", "moderate", "high", "no_data", "not_needed")

# Level -> overall severity name (no_data contributes nothing).
SEVERITY_BY_LEVEL = {
    "none": "LOW",
    "not_needed": "LOW",
    "mild": "MEDIUM",
    "moderate": "HIGH",
    "high": "CRITICAL",
}

_RDI_NOTE_LEVELS = ("mild", "moderate", "high")


@dataclass(frozen=True)
class WaterStressIndicator:
    level: str  # none | mild | moderate | high | no_data | not_needed
    method: str  # cwsi_sensor | balance | none
    value: float | None = None
    phase_note: str | None = None  # "rdi" | None
    baseline_id: str | None = None
    source_ids: tuple[str, ...] = ()


def level_from_cwsi(cwsi: float) -> str:
    if cwsi >= CWSI_CUTS["high"]:
        return "high"
    if cwsi >= CWSI_CUTS["moderate"]:
        return "moderate"
    if cwsi >= CWSI_CUTS["mild"]:
        return "mild"
    return "none"


def level_from_index(index: float) -> str:
    """Level from WaterStress.index (= 1 - Ks); compared on Ks, rounded like the index."""
    ks = round(1.0 - index, 3)
    if ks >= KS_INDEX_CUTS["none_ks_min"]:
        return "none"
    if ks >= KS_INDEX_CUTS["mild_ks_min"]:
        return "mild"
    if ks >= KS_INDEX_CUTS["moderate_ks_min"]:
        return "moderate"
    return "high"


# Stages in which a water deficit costs most yield: flowering and yield formation (FAO-33,
# Doorenbos & Kassam 1979). ASSUMPTION: owner-approved 2026-11-11; FAO-33 names the periods,
# not this list of stage names
RAINFED_SENSITIVE_STAGES = frozenset({"flowering", "grain_filling", "fruit_set", "kernel_fill"})


def severity_name(level: str, *, regime: str | None = None, stage: str | None = None) -> str | None:
    """Severity name for a level, or None when the level adds no severity.

    A rainfed parcel cannot be irrigated, so its water stress is a state to watch: at most
    MEDIUM, and HIGH only for a high level in a stage of ``RAINFED_SENSITIVE_STAGES``.
    Any other regime (irrigated or unknown) keeps ``SEVERITY_BY_LEVEL``.
    """
    name = SEVERITY_BY_LEVEL.get(level)
    if regime != "rainfed" or name is None:
        return name
    if level == "moderate":
        return "MEDIUM"
    if level == "high":
        return "HIGH" if stage in RAINFED_SENSITIVE_STAGES else "MEDIUM"
    return name


def _baseline_sources(cwsi: CWSIResult, reference: WaterStressReference | None) -> tuple[str, ...]:
    if reference is None or cwsi.baseline_id is None:
        return ()
    for b in reference.baselines:
        if b.id == cwsi.baseline_id:
            return (b.source_id,) if b.source_id else ()
    return ()


def resolve_indicator(
    cwsi: CWSIResult | None,
    water_stress: WaterStress | None,
    flags: StageWaterFlags | None,
    *,
    reference: WaterStressReference | None = None,
) -> WaterStressIndicator:
    """Sensor CWSI wins over the Ks index; no inputs is no_data; stage flags then apply."""
    if cwsi is not None:
        level, method, value = level_from_cwsi(cwsi.cwsi), "cwsi_sensor", cwsi.cwsi
        baseline_id = cwsi.baseline_id
        sources = _baseline_sources(cwsi, reference)
    elif water_stress is not None and water_stress.index is not None:
        level, method, value = level_from_index(water_stress.index), "balance", water_stress.index
        baseline_id, sources = None, ()
    else:
        level, method, value, baseline_id, sources = "no_data", "none", None, None, ()

    phase_note = None
    if flags is not None:
        flag_sources = tuple(flags.source_ids)
        if flags.water_sensitive is False:
            level, sources = "not_needed", flag_sources
        elif flags.rdi_tolerant is True and level in _RDI_NOTE_LEVELS:
            phase_note, sources = "rdi", sources + tuple(s for s in flag_sources if s not in sources)
    return WaterStressIndicator(
        level=level, method=method, value=value, phase_note=phase_note,
        baseline_id=baseline_id, source_ids=sources,
    )
