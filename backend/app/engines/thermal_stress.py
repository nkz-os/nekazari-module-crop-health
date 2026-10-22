"""Thermal Stress Engine — heat stress and frost risk in real time.

Uses leaf temperature from IR sensor and air temperature from weather API.
Thresholds per species are queried from BioOrchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ThermalThresholds:
    heat_damage_c: float = 35.0      # leaf temp above which damage begins
    frost_damage_c: float = -2.0     # air temp below which damage begins
    heat_accum_hours: int = 6        # hours above threshold to flag stress


@dataclass
class ThermalResult:
    heat_stress_hours: float = 0.0
    frost_hours: float = 0.0
    condition: str = "no_stress"  # no_stress | heat_warning | heat_stress | frost_warning | frost_damage
    severity: str = "LOW"         # LOW | MEDIUM | HIGH | CRITICAL
    data_fidelity: str = "regional_proxy"


def evaluate_thermal_stress(
    leaf_temp: float | None,
    air_temp: float | None,
    air_temp_min_24h: float | None = None,
    thresholds: ThermalThresholds | None = None,
    fidelity: str = "regional_proxy",
) -> ThermalResult:
    """Evaluate heat and frost stress from temperature data.

    Args:
        leaf_temp: Current canopy temperature from IR sensor (°C)
        air_temp: Current air temperature (°C)
        air_temp_min_24h: Minimum air temp in last 24h (°C)
        thresholds: Species-specific damage thresholds
        fidelity: dataFidelity level from input sources

    Returns:
        ThermalResult with condition and severity
    """
    th = thresholds or ThermalThresholds()
    result = ThermalResult(data_fidelity=fidelity)

    if leaf_temp is not None:
        if leaf_temp > th.heat_damage_c:
            result.heat_stress_hours = 1.0  # current reading; accumulation needs timeseries
            excess = leaf_temp - th.heat_damage_c
            if excess > 5:
                result.condition = "heat_stress"
                result.severity = "CRITICAL"
            elif excess > 2:
                result.condition = "heat_stress"
                result.severity = "HIGH"
            else:
                result.condition = "heat_warning"
                result.severity = "MEDIUM"

    if air_temp_min_24h is not None and air_temp_min_24h < th.frost_damage_c:
        result.frost_hours = 1.0  # placeholder; real accumulation needs timeseries
        deficit = th.frost_damage_c - air_temp_min_24h
        if deficit > 5:
            frost_condition = "frost_damage"
            frost_severity = "CRITICAL"
        elif deficit > 2:
            frost_condition = "frost_damage"
            frost_severity = "HIGH"
        else:
            frost_condition = "frost_warning"
            frost_severity = "MEDIUM"

        # Frost takes priority over heat in severity
        if frost_severity == "CRITICAL" or result.severity != "CRITICAL":
            result.condition = frost_condition
            result.severity = frost_severity

    return result
