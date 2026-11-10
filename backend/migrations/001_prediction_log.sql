-- Append-only record of every prediction emitted by crop-health.
-- Idempotent; applied by a superuser (the owner), never by the application role.

CREATE SCHEMA IF NOT EXISTS crop_health;

CREATE TABLE IF NOT EXISTS crop_health.prediction_log (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id     TEXT        NOT NULL,
  parcel_id     TEXT        NOT NULL,   -- AgriParcel URN
  season_start  DATE        NOT NULL,   -- sowing date of the cycle
  crop          TEXT        NOT NULL,   -- species code as the platform resolved it
  kind          TEXT        NOT NULL CHECK (kind IN ('phenology', 'yield')),
  model         TEXT        NOT NULL,   -- who predicted
  model_version TEXT        NOT NULL,
  as_of         DATE        NOT NULL,   -- last closed weather day the prediction used
  emitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload       JSONB       NOT NULL,   -- what was predicted
  inputs        JSONB       NOT NULL,   -- what it was predicted from
  UNIQUE (tenant_id, parcel_id, season_start, kind, model, model_version, as_of)
);

CREATE INDEX IF NOT EXISTS prediction_log_lookup_idx
  ON crop_health.prediction_log (tenant_id, parcel_id, kind, season_start, as_of);

CREATE OR REPLACE FUNCTION crop_health.prediction_log_immutable()
RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
  RAISE EXCEPTION 'crop_health.prediction_log is append-only (% blocked)', TG_OP;
END;
$fn$;

DROP TRIGGER IF EXISTS prediction_log_append_only ON crop_health.prediction_log;
CREATE TRIGGER prediction_log_append_only
  BEFORE UPDATE OR DELETE ON crop_health.prediction_log
  FOR EACH ROW EXECUTE FUNCTION crop_health.prediction_log_immutable();

DROP TRIGGER IF EXISTS prediction_log_no_truncate ON crop_health.prediction_log;
CREATE TRIGGER prediction_log_no_truncate
  BEFORE TRUNCATE ON crop_health.prediction_log
  FOR EACH STATEMENT EXECUTE FUNCTION crop_health.prediction_log_immutable();

-- Application role: read and append only. Skipped when the role does not exist.
DO $grants$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nkz_module_crop_health') THEN
    GRANT USAGE ON SCHEMA crop_health TO nkz_module_crop_health;
    GRANT SELECT, INSERT ON crop_health.prediction_log TO nkz_module_crop_health;
  ELSE
    RAISE NOTICE 'role nkz_module_crop_health not found: grants skipped';
  END IF;
END
$grants$;
