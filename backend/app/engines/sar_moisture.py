"""SAR Moisture/Flood Engine.

Mixed approach for SAR (Synthetic Aperture Radar) data from Sentinel-1:
- For Rice (ORYSA): Detects flood stage (specular reflection).
- For other irrigated crops: Estimates surface soil moisture and detects waterlogging risk.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SARResult:
    is_flooded: bool = False
    flood_stage: str = "none"           # none | flooded | emerging | dry (for rice)
    surface_moisture_index: float = 0.5   # 0.0 to 1.0
    waterlogging_risk: str = "low"      # low | medium | high
    data_fidelity: str = "modeled_opendata"


def evaluate_sar_moisture(
    species_eppo: str,
    backscatter_vv: float | None,
    backscatter_vh: float | None,
    fidelity: str = "modeled_opendata",
) -> SARResult:
    """Evaluate SAR backscatter for flood/moisture.

    Args:
        species_eppo: EPPO code of the crop (e.g., ORYSA for rice).
        backscatter_vv: VV polarization backscatter (dB).
        backscatter_vh: VH polarization backscatter (dB).
        fidelity: dataFidelity level.

    Returns:
        SARResult.
    """
    result = SARResult(data_fidelity=fidelity)

    if backscatter_vv is None or backscatter_vh is None:
        return result

    # Simplified heuristic model for demonstration
    # In a real scenario, this would use a Water Cloud Model (WCM) or adaptive thresholds.

    if species_eppo == "ORYSA":
        # Rice flood logic
        # Very low VV (<-15 dB) indicates open water (specular reflection)
        # Increasing VH indicates canopy emergence
        if backscatter_vv < -14.0:
            result.is_flooded = True
            result.flood_stage = "flooded"
        elif -14.0 <= backscatter_vv < -10.0 and backscatter_vh > -20.0:
            result.is_flooded = True
            result.flood_stage = "emerging"
        else:
            result.is_flooded = False
            result.flood_stage = "dry"
        
        # Surface moisture isn't the primary metric during flood
        result.surface_moisture_index = 1.0 if result.is_flooded else 0.5
        result.waterlogging_risk = "low" # Rice likes water

    else:
        # Other crops: Moisture & Waterlogging
        # Higher backscatter generally correlates with higher moisture (roughness being equal)
        # We map a typical agricultural VV range (-15 dry to -5 wet) to an index 0-1
        norm_moisture = (backscatter_vv - (-15.0)) / (-5.0 - (-15.0))
        norm_moisture = max(0.0, min(1.0, norm_moisture))
        result.surface_moisture_index = round(norm_moisture, 2)

        # Extreme backscatter (+ sudden increase vs baseline, though we only have single timestamp here)
        # acts as a proxy for surface inundation.
        if backscatter_vv > -6.0:
            result.waterlogging_risk = "high"
        elif backscatter_vv > -8.0:
            result.waterlogging_risk = "medium"
        else:
            result.waterlogging_risk = "low"

    return result
