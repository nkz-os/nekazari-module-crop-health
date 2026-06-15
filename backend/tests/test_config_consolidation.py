"""Settings exposes internal_service_secret; no os.getenv duplication of settings."""

import pathlib

from app.config import Settings


def test_settings_has_internal_service_secret():
    assert hasattr(Settings(), "internal_service_secret")


def test_no_getenv_for_orion_or_weather_in_assessments():
    src = pathlib.Path("app/api/assessments.py").read_text()
    assert 'os.getenv("ORION_LD_URL"' not in src
    assert 'os.getenv("ORION_LD_CONTEXT"' not in src
    assert 'os.getenv("WEATHER_DB_URL"' not in src


def test_no_getenv_for_internal_secret_in_setup():
    src = pathlib.Path("app/api/setup.py").read_text()
    assert 'os.getenv("INTERNAL_SERVICE_SECRET"' not in src
