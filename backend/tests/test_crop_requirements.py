"""Tests for CropRequirements schema + serialization."""
from app.schemas import CropRequirements


def test_crop_requirements_defaults():
    cr = CropRequirements()
    assert cr.irrigation_mm is None
    assert cr.n_kg_ha is None


def test_crop_requirements_with_values():
    cr = CropRequirements(irrigation_mm=35.0, n_kg_ha=45.0, p2o5_kg_ha=20.0)
    assert cr.irrigation_mm == 35.0
    assert cr.n_kg_ha == 45.0
    assert cr.p2o5_kg_ha == 20.0
