import type { SeasonInfo, YieldForecastRecord } from '../types/yieldForecast';

const URN_PREFIX = 'urn:ngsi-ld:AgriParcel:';

export interface EstimateRow {
  providerId: string;
  basis: string;
  low: number;
  high: number;
  median: number | null;
  validation: 'validated' | 'experimental' | 'not_applicable';
}

export function toParcelUrn(id: string): string {
  return id.startsWith(URN_PREFIX) ? id : `${URN_PREFIX}${id}`;
}

/** One row per C4 estimate (never averaged); unvalidated and figure-less ones are not shown. */
export function rowsFor(record: YieldForecastRecord): EstimateRow[] {
  const rows: EstimateRow[] = [];
  for (const e of record.estimates ?? []) {
    const status = e.validation?.status;
    if (status !== 'validated' && status !== 'experimental' && status !== 'not_applicable') continue;
    const low = e.range?.low ?? e.percentiles?.p10;
    const high = e.range?.high ?? e.percentiles?.p90;
    if (low == null || high == null) continue;
    rows.push({ providerId: e.provider_id, basis: e.basis, low, high,
      median: e.range ? null : e.percentiles?.p50 ?? null, validation: status });
  }
  return rows;
}

/** Bioorch's simulation view, pre-filled so it joins the day's in-season job (params agreed with bioorch). */
export function detailLink(parcelId: string, season: SeasonInfo | null | undefined): string {
  const q = new URLSearchParams({ parcel: toParcelUrn(parcelId), view: 'simulation' });
  if (season) {
    q.set('crop_slug', season.crop);
    q.set('sowing_date', season.sowing.date);
    q.set('irrigation', season.regime === 'irrigated' ? 'full' : 'rainfed');
  }
  return `/bioorchestrator?${q.toString()}`;
}

/** A refresh is over when the record moved on, or when it stopped being refreshed. */
export function refreshSettled(before: YieldForecastRecord, after: YieldForecastRecord): boolean {
  if (!after.refreshing) return true;
  return after.computed_at !== before.computed_at || after.attempted_at !== before.attempted_at;
}
