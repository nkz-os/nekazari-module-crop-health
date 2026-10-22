"""Tests for SAR moisture/flood engine."""
from app.engines.sar_moisture import evaluate_sar_moisture


def test_sar_rice_flooded():
    """Rice with VV < -14 dB → flooded stage."""
    result = evaluate_sar_moisture(
        species_eppo="ORYSA",
        backscatter_vv=-16.0,
        backscatter_vh=-22.0,
    )
    assert result.is_flooded is True
    assert result.flood_stage == "flooded"
    assert result.surface_moisture_index == 1.0
    assert result.waterlogging_risk == "low"


def test_sar_rice_emerging():
    """Rice with VV between -14 and -10, VH > -20 → emerging."""
    result = evaluate_sar_moisture(
        species_eppo="ORYSA",
        backscatter_vv=-12.0,
        backscatter_vh=-18.0,
    )
    assert result.is_flooded is True
    assert result.flood_stage == "emerging"


def test_sar_rice_dry():
    """Rice with VV > -10 → dry stage."""
    result = evaluate_sar_moisture(
        species_eppo="ORYSA",
        backscatter_vv=-8.0,
        backscatter_vh=-15.0,
    )
    assert result.is_flooded is False
    assert result.flood_stage == "dry"


def test_sar_other_crop_dry():
    """Wheat with low VV → low moisture index, no waterlogging."""
    result = evaluate_sar_moisture(
        species_eppo="TRZAX",
        backscatter_vv=-14.0,
        backscatter_vh=-20.0,
    )
    assert result.is_flooded is False
    assert result.flood_stage == "none"
    assert 0.0 <= result.surface_moisture_index <= 0.3
    assert result.waterlogging_risk == "low"


def test_sar_other_crop_wet():
    """Wheat with high VV → high moisture, waterlogging risk."""
    result = evaluate_sar_moisture(
        species_eppo="TRZAX",
        backscatter_vv=-5.0,
        backscatter_vh=-12.0,
    )
    assert result.waterlogging_risk == "high"
    assert result.surface_moisture_index >= 0.7


def test_sar_other_crop_medium_moisture():
    """Wheat with moderate VV."""
    result = evaluate_sar_moisture(
        species_eppo="TRZAX",
        backscatter_vv=-7.0,
        backscatter_vh=-16.0,
    )
    assert result.waterlogging_risk == "medium"
    assert 0.4 < result.surface_moisture_index < 0.9


def test_sar_no_data():
    """None backscatter → default result, no crash."""
    result = evaluate_sar_moisture(
        species_eppo="TRZAX",
        backscatter_vv=None,
        backscatter_vh=None,
    )
    assert result.is_flooded is False
    assert result.flood_stage == "none"
    assert result.surface_moisture_index == 0.5
