"""The migration file carries the contract's key statements (no live database here)."""
import re
from pathlib import Path

SQL = (Path(__file__).resolve().parents[1] / "migrations" / "001_prediction_log.sql").read_text()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_schema_and_table_are_idempotent():
    n = _norm(SQL)
    assert "CREATE SCHEMA IF NOT EXISTS crop_health" in n
    assert "CREATE TABLE IF NOT EXISTS crop_health.prediction_log" in n
    assert "CHECK (kind IN ('phenology', 'yield'))" in n
    assert "UNIQUE (tenant_id, parcel_id, season_start, kind, model, model_version, as_of)" in n
    assert "CREATE INDEX IF NOT EXISTS" in n
    assert "(tenant_id, parcel_id, kind, season_start, as_of)" in n


def test_append_only_trigger():
    n = _norm(SQL)
    assert "BEFORE UPDATE OR DELETE ON crop_health.prediction_log" in n
    assert "RAISE EXCEPTION" in n
    assert "DROP TRIGGER IF EXISTS" in n or "CREATE OR REPLACE TRIGGER" in n


def test_truncate_is_blocked():
    assert "BEFORE TRUNCATE ON crop_health.prediction_log" in _norm(SQL)


def test_grants_are_select_insert_only_and_guarded():
    n = _norm(SQL)
    assert "pg_roles" in n and "nkz_module_crop_health" in n
    assert "GRANT USAGE ON SCHEMA crop_health" in n
    assert "GRANT SELECT, INSERT ON crop_health.prediction_log" in n
    assert not re.search(r"GRANT[^;]*\b(UPDATE|DELETE|ALL)\b", n)
