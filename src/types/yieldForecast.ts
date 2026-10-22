export interface C4Estimate {
  provider_id: string;
  provider_version?: string;
  basis: string;
  unit?: string;
  percentiles?: { p10: number; p50: number; p90: number } | null;
  range?: { low: number; high: number } | null;
  validation: { status: 'validated' | 'experimental' | 'unvalidated' | 'not_applicable'; scope?: string | null };
  warnings?: string[];
}

export interface SeasonInfo {
  status: 'in_season' | 'complete';
  as_of: string | null;
  crop: string;
  regime: 'rainfed' | 'irrigated';
  sowing: { date: string; source: string; provenance: string };
  harvest_date?: string | null;
  computed_at?: string | null;
}

export interface YieldForecastRecord {
  status: 'not_computed' | 'done' | 'season_ended' | 'unavailable' | 'failed';
  estimates?: C4Estimate[];
  /** Providers that gave no figure, and why (C4). */
  unavailable?: { provider_id?: string; reason: string; code?: string | null }[];
  season?: SeasonInfo | null;
  reason?: string;
  code?: string | null;
  computed_at?: string;
  attempted_at?: string;
  last_error?: { reason: string; code: string | null; at: string } | null;
  refreshing: boolean;
}
