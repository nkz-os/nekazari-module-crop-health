"""Crop Vigor Engine — composite index from vegetation + CWSI + GDD.

Combines satellite vegetation indices (NDVI, EVI, SAVI, GNDVI, NDRE)
with ground-truth CWSI and phenological stage from GDD.
Auto-selects the optimal vegetation index per phenological stage.
"""

from __future__ import annotations

from dataclasses import dataclass

# Index selection per phenological stage
# Rationale: SAVI for bare soil, NDRE for nitrogen stress, GNDVI for chlorophyll
STAGE_INDEX_PREFERENCE: dict[str, str] = {
    "emergence": "SAVI",
    "vegetative": "GNDVI",
    "stem_elongation": "NDRE",
    "flowering": "NDRE",
    "fruit_set": "NDVI",
    "pit_hardening": "NDVI",
    "fruit_growth": "NDVI",
    "kernel_fill": "NDVI",
    "veraison": "GNDVI",
    "ripening": "NDVI",
    "senescence": "NDVI",
}


@dataclass
class VigorResult:
    vigor_index: float = 0.0       # 0-1, where 0 = dead, 1 = optimal
    growth_anomaly: float = 0.0    # deviation from expected NDVI for stage
    index_used: str = "NDVI"
    condition: str = "normal"      # normal | below_expected | above_expected | anomalous_senescence
    data_fidelity: str = "modeled_opendata"


def evaluate_vigor(
    ndvi: float | None = None,
    evi: float | None = None,
    savi: float | None = None,
    gndvi: float | None = None,
    ndre: float | None = None,
    cwsi: float | None = None,
    stage: str = "vegetative",
    expected_ndvi: float | None = None,
    fidelity: str = "modeled_opendata",
) -> VigorResult:
    """Evaluate crop vigor from vegetation indices and CWSI.

    Args:
        ndvi, evi, savi, gndvi, ndre: Available vegetation indices
        cwsi: Crop Water Stress Index (0-1)
        stage: Current phenological stage name
        expected_ndvi: Reference NDVI for this stage (from BioOrchestrator)
        fidelity: dataFidelity level

    Returns:
        VigorResult with composite index and anomaly detection
    """
    result = VigorResult(data_fidelity=fidelity)

    # Determine which index to use
    preferred = STAGE_INDEX_PREFERENCE.get(stage, "NDVI")
    index_map = {"NDVI": ndvi, "EVI": evi, "SAVI": savi, "GNDVI": gndvi, "NDRE": ndre}

    # Try preferred index, fall back to NDVI
    vi_value = index_map.get(preferred)
    if vi_value is None:
        vi_value = ndvi
        preferred = "NDVI"

    result.index_used = preferred

    if vi_value is not None:
        # Base vigor from vegetation index (0-1 scale)
        vi_vigor = max(0.0, min(1.0, vi_value / 0.9))

        # Penalize for water stress if CWSI available
        if cwsi is not None:
            cwsi_penalty = cwsi * 0.4  # CWSI contributes up to 40% penalty
            result.vigor_index = max(0.0, vi_vigor - cwsi_penalty)
        else:
            result.vigor_index = vi_vigor

        # Growth anomaly vs expected
        if expected_ndvi is not None:
            result.growth_anomaly = vi_value - expected_ndvi
            if result.growth_anomaly < -0.15:
                result.condition = "below_expected"
            elif result.growth_anomaly < -0.30:
                result.condition = "anomalous_senescence"
            elif result.growth_anomaly > 0.10:
                result.condition = "above_expected"

    return result
