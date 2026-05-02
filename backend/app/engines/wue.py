"""Water Use Efficiency Engine — biomass gain per unit of water applied.

Conditional on irrigation data availability:
  - operational: MQTT/Modbus irrigation meter data available
  - advisory: manual irrigation log via UI
  - suppressed: no irrigation data (UI shows activation instructions)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WUEResult:
    wue_kg_m3: float | None = None       # kg biomass per m³ water
    biomass_estimated_kg: float = 0.0     # estimated biomass gain
    water_applied_mm: float = 0.0         # total irrigation water applied
    status: str = "suppressed"            # operational | advisory | suppressed
    trend: str = "stable"                 # improving | stable | declining
    data_fidelity: str = "suppressed"


def evaluate_wue(
    ndvi_integrated: float | None = None,
    irrigation_applied_mm: float | None = None,
    irrigation_source: str = "none",      # measured_flow | declared_volume | none
    previous_wue: float | None = None,
    fidelity: str = "suppressed",
) -> WUEResult:
    """Calculate Water Use Efficiency.

    WUE = biomass_estimated / water_applied

    Biomass is roughly estimated from NDVI integrated over time using
    the Monteith (1972) light-use efficiency approach simplified for NDVI proxy.

    Args:
        ndvi_integrated: NDVI integrated over season (dimensionless × days)
        irrigation_applied_mm: Total irrigation water applied (mm)
        irrigation_source: How water data was obtained
        previous_wue: Previous WUE value for trend detection
        fidelity: dataFidelity level

    Returns:
        WUEResult with status based on data availability
    """
    result = WUEResult(data_fidelity=fidelity)

    if irrigation_source == "none" or irrigation_applied_mm is None or irrigation_applied_mm <= 0:
        result.status = "suppressed"
        result.trend = "stable"
        return result

    if ndvi_integrated is None:
        result.status = "suppressed"
        return result

    # Rough biomass estimation from NDVI integral
    # NDVI integrated × radiation-use efficiency proxy ≈ gC/m²
    # Convert to kg/ha: gC/m² × 10 = kg biomass/ha
    # Simplified: biomass_kg = ndvi_integrated × 1000 / harvest_index
    harvest_index = 0.45  # generic for grain crops; configurable per species
    result.biomass_estimated_kg = (ndvi_integrated * 1000) / harvest_index

    # WUE = kg biomass / m³ water = kg / (mm × 10)
    result.water_applied_mm = irrigation_applied_mm
    result.wue_kg_m3 = round(result.biomass_estimated_kg / (irrigation_applied_mm * 10), 2)

    if irrigation_source == "measured_flow":
        result.status = "operational"
    elif irrigation_source == "declared_volume":
        result.status = "advisory"

    if previous_wue and result.wue_kg_m3:
        delta = result.wue_kg_m3 - previous_wue
        if delta > 0.5:
            result.trend = "improving"
        elif delta < -0.5:
            result.trend = "declining"

    return result
