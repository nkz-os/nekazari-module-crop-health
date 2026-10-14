import { describe, expect, it } from 'vitest';
import { detailLink, refreshSettled, rowsFor, toParcelUrn } from './yieldForecastModel';
import type { YieldForecastRecord } from '../types/yieldForecast';

const rec = (estimates: any[]): YieldForecastRecord => ({ status: 'done', estimates, refreshing: false });

describe('rowsFor', () => {
  it('keeps every provider, in order, never averaged', () => {
    const rows = rowsFor(rec([
      { provider_id: 'aquacrop', basis: 'gap_corrected', range: { low: 3.1, high: 4.2 }, validation: { status: 'experimental' } },
      { provider_id: 'wofost', basis: 'water_limited', percentiles: { p10: 4, p50: 5, p90: 6 }, validation: { status: 'not_applicable' } },
    ]));
    expect(rows.map((r) => r.providerId)).toEqual(['aquacrop', 'wofost']);
    expect(rows[0]).toMatchObject({ low: 3.1, high: 4.2, median: null, validation: 'experimental' });
    expect(rows[1]).toMatchObject({ low: 4, high: 6, median: 5 });
  });
  it('hides unvalidated', () => {
    expect(rowsFor(rec([{ provider_id: 'x', basis: 'potential', range: { low: 1, high: 2 }, validation: { status: 'unvalidated' } }]))).toEqual([]);
  });
  it('rowsFor skips an estimate without figures', () => {
    expect(rowsFor(rec([{ provider_id: 'x', basis: 'potential', validation: { status: 'validated' } }]))).toEqual([]);
  });
  it('is empty without estimates', () => {
    expect(rowsFor({ status: 'not_computed', refreshing: false })).toEqual([]);
  });
});

describe('detailLink', () => {
  it('sends the agreed pre-fill params with the parcel URN', () => {
    const url = detailLink('d2e5', { status: 'in_season', as_of: null, crop: 'TRZAX', regime: 'irrigated',
      sowing: { date: '2026-10-20', source: 'crop_cycle', provenance: 'actual' } });
    expect(url).toBe('/bioorchestrator?parcel=urn%3Angsi-ld%3AAgriParcel%3Ad2e5&view=simulation&crop_slug=TRZAX&sowing_date=2026-10-20&irrigation=full');
  });
  it('opens the parcel alone without a season', () => {
    expect(detailLink('urn:ngsi-ld:AgriParcel:p', null)).toBe('/bioorchestrator?parcel=urn%3Angsi-ld%3AAgriParcel%3Ap&view=simulation');
  });
});

describe('toParcelUrn / refreshSettled', () => {
  it('normalises a bare id', () => expect(toParcelUrn('abc')).toBe('urn:ngsi-ld:AgriParcel:abc'));
  it('settles when computed_at or attempted_at moves', () => {
    const a = { status: 'done', refreshing: true, computed_at: '1', attempted_at: '1' } as YieldForecastRecord;
    expect(refreshSettled(a, { ...a })).toBe(false);
    expect(refreshSettled(a, { ...a, attempted_at: '2' })).toBe(true);
    expect(refreshSettled({ status: 'not_computed', refreshing: true }, { status: 'unavailable', reason: 'not_sown', refreshing: false })).toBe(true);
  });
});
