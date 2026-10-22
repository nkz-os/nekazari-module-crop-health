"""VHI/ASIS Engine — Agricultural Drought Early Warning (FAO Cap. 6).

Implements the Vegetation Health Index (VHI) and its components:
- VCI (Vegetation Condition Index): Compares current NDVI to historical min/max.
- TCI (Temperature Condition Index): Compares current Temperature to historical min/max.
- VHI: Weighted combination of VCI and TCI (typically 0.5/0.5).

Used for early drought detection and yield forecasting proxy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VHIResult:
    vci: float | None = None          # 0-100
    tci: float | None = None          # 0-100
    vhi: float | None = None          # 0-100
    asi_pct: float | None = None      # % area VHI < 35
    tci_source: str = "none"  # iot_canopy | iot_soil | satellite_lst | weather_proxy | landsat_tirs
    data_fidelity: str = "none"       # onsite_calibrated | onsite_uncalibrated | regional_proxy | modeled_opendata


def evaluate_vhi(
    ndvi_actual: float | None,
    ndvi_min: float | None,
    ndvi_max: float | None,
    temp_actual: float | None,
    temp_min: float | None,
    temp_max: float | None,
    temp_source: str = "none",
    fidelity: str = "none",
    alpha: float = 0.5,
    beta: float = 0.5,
) -> VHIResult:
    """Calculate VHI per Kogan 1995 / Rojas 2016.

    Args:
        ndvi_actual: Current period NDVI
        ndvi_min: Historical absolute minimum NDVI for this dekad/period
        ndvi_max: Historical absolute maximum NDVI for this dekad/period
        temp_actual: Current period Temperature (LST or air)
        temp_min: Historical absolute minimum Temperature for this dekad
        temp_max: Historical absolute maximum Temperature for this dekad
        temp_source: Where the temperature data came from
        fidelity: dataFidelity level of the temperature data
        alpha: Weight for VCI
        beta: Weight for TCI

    Returns:
        VHIResult with computed indices (0-100 scale, lower is more stressed)
    """
    result = VHIResult(tci_source=temp_source, data_fidelity=fidelity)

    if ndvi_actual is not None and ndvi_min is not None and ndvi_max is not None:
        if ndvi_max > ndvi_min:
            n_act = max(ndvi_min, min(ndvi_max, ndvi_actual))
            result.vci = round(((n_act - ndvi_min) / (ndvi_max - ndvi_min)) * 100, 2)
        else:
            result.vci = 50.0

    if temp_actual is not None and temp_min is not None and temp_max is not None:
        if temp_max > temp_min:
            t_act = max(temp_min, min(temp_max, temp_actual))
            # TCI formulation is inverted: higher temp = lower index (more stress)
            result.tci = round(((temp_max - t_act) / (temp_max - temp_min)) * 100, 2)
        else:
            result.tci = 50.0

    if result.vci is not None and result.tci is not None:
        result.vhi = round(alpha * result.vci + beta * result.tci, 2)

    return result
