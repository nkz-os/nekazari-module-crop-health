// Contract 2.11 of the BioOrchestrator planning API, relayed by crop-health.
export type Regime = string;
export interface Unavailable { provider_id: string; reason: string; code?: string }

export interface WaterLossBand { p10: number; p50: number; p90: number }
export interface WaterLossMilestone { key: string; date: string; basis: 'thermal_time_no_stress_delay' }
export interface WaterLossStage {
  index: number; key: 'establishment' | 'canopy_growth' | 'max_canopy' | 'senescence';
  start: string | null; end: string | null; state: 'complete' | 'in_progress' | 'not_reached';
  milestones: WaterLossMilestone[] | null; milestones_reason: string | null;
  gain_t_ha_model: number | WaterLossBand | null;
  gain_pct_of_potential: number | WaterLossBand | null;
  end_in_relief_run: string | null;
}
export interface WaterLossResult {
  total: {
    water_gap_pct: number | null; water_gap_band: WaterLossBand | null;
    water_limited_t_ha: number | WaterLossBand | null; potential_t_ha: number | WaterLossBand | null;
  };
  stages: WaterLossStage[];
  stage_bounds_basis: 'rainfed_simulation'; milestones_basis: 'thermal_time_no_stress_delay';
  yield_basis: { moisture: string; grain_moisture_pct?: number | null; [key: string]: unknown };
  validation: { status: 'validated_forecast_crop' | 'unvalidated'; note: string };
  label: string; notes: string[]; sources: { short: string; detail: string }[]; engine_version: string; warnings: string[];
}
export interface WaterLossResponse {
  contract_version: string; provider_id: 'aquacrop_water_loss';
  state: 'unavailable' | 'queued' | 'running' | 'done' | 'failed';
  done: number; total: number | null; job_id: string | null; unavailable: Unavailable[];
  season: {
    status: 'in_season' | 'complete'; as_of: string | null; crop: string; regime: Regime;
    sowing: { date: string; source: 'crop_cycle'; provenance: 'actual' | 'declared' };
    n_years: number; ensemble: { n_years: number; years: number[] } | null;
    cycle: 'current' | 'previous'; harvest_recorded: string | null;
    computed_at: string | null; provider_version: string;
  } | null;
  result: WaterLossResult | null;
}
