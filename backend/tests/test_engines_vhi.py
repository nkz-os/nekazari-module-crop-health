"""Tests for VHI/ASIS engine (FAO Cap. 6)."""
from app.engines.vhi_asis import evaluate_vhi


def test_vhi_both_components_available():
    """With both NDVI and temperature, VHI = 0.5*VCI + 0.5*TCI."""
    result = evaluate_vhi(
        ndvi_actual=0.5,
        ndvi_min=0.15,
        ndvi_max=0.85,
        temp_actual=30.0,
        temp_min=10.0,
        temp_max=45.0,
        temp_source="iot_canopy",
        fidelity="onsite_calibrated",
    )
    assert result.vci is not None
    assert result.tci is not None
    assert result.vhi is not None
    assert 0.0 <= result.vci <= 100.0
    assert 0.0 <= result.tci <= 100.0
    assert 0.0 <= result.vhi <= 100.0
    assert result.tci_source == "iot_canopy"
    assert result.data_fidelity == "onsite_calibrated"

    # NDVI=0.5 → VCI = (0.5-0.15)/(0.85-0.15)*100 = 50.0
    assert result.vci == 50.0
    # Temp=30 → TCI = (45-30)/(45-10)*100 ≈ 42.86
    assert abs(result.tci - 42.86) < 0.1
    # VHI = 0.5*50 + 0.5*42.86 = 46.43
    assert abs(result.vhi - 46.43) < 0.1


def test_vhi_high_stress():
    """Very low NDVI and high temp → low VHI (stressed)."""
    result = evaluate_vhi(
        ndvi_actual=0.2,
        ndvi_min=0.15,
        ndvi_max=0.85,
        temp_actual=42.0,
        temp_min=10.0,
        temp_max=45.0,
    )
    assert result.vci is not None and result.vci < 20.0
    assert result.tci is not None and result.tci < 20.0
    assert result.vhi is not None and result.vhi < 20.0


def test_vhi_no_stress():
    """High NDVI and cool temp → high VHI (healthy)."""
    result = evaluate_vhi(
        ndvi_actual=0.8,
        ndvi_min=0.15,
        ndvi_max=0.85,
        temp_actual=15.0,
        temp_min=10.0,
        temp_max=45.0,
    )
    assert result.vci is not None and result.vci > 80.0
    assert result.tci is not None and result.tci > 80.0
    assert result.vhi is not None and result.vhi > 80.0


def test_vhi_ndvi_only():
    """If temperature is None, only VCI is computed."""
    result = evaluate_vhi(
        ndvi_actual=0.5,
        ndvi_min=0.15,
        ndvi_max=0.85,
        temp_actual=None,
        temp_min=10.0,
        temp_max=45.0,
    )
    assert result.vci is not None
    assert result.tci is None
    assert result.vhi is None


def test_vhi_temperature_only():
    """If NDVI is None, only TCI is computed."""
    result = evaluate_vhi(
        ndvi_actual=None,
        ndvi_min=0.15,
        ndvi_max=0.85,
        temp_actual=25.0,
        temp_min=10.0,
        temp_max=45.0,
    )
    assert result.vci is None
    assert result.tci is not None
    assert result.vhi is None


def test_vhi_clamps_extreme_values():
    """Values outside historical range are clamped."""
    result = evaluate_vhi(
        ndvi_actual=1.0,
        ndvi_min=0.15,
        ndvi_max=0.85,
        temp_actual=50.0,
        temp_min=10.0,
        temp_max=45.0,
    )
    assert result.vci == 100.0
    assert result.tci == 0.0


def test_vhi_equal_min_max_returns_50():
    """Degenerate case: min==max → 50 for both indices."""
    result = evaluate_vhi(
        ndvi_actual=0.5,
        ndvi_min=0.5,
        ndvi_max=0.5,
        temp_actual=20.0,
        temp_min=20.0,
        temp_max=20.0,
    )
    assert result.vci == 50.0
    assert result.tci == 50.0
    assert result.vhi == 50.0
