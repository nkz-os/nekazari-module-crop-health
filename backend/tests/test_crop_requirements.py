"""Tests for CropRequirements schema + serialization."""
from app.schemas import CropRequirements


def test_crop_requirements_defaults():
    cr = CropRequirements()
    assert cr.irrigation_mm is None
    assert cr.water_deficit_mm is None


def test_crop_requirements_carries_no_npk_fields():
    fields = set(CropRequirements.model_fields)
    assert not fields & {"n_kg_ha", "p2o5_kg_ha", "k2o_kg_ha"}
