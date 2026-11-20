import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t: (k: string, o?: any) => (o ? `${k}:${JSON.stringify(o)}` : k), i18n: { language: 'es' } }),
}));
vi.mock('../api/cropHealthApi', () => ({
  getYieldForecast: vi.fn(), refreshYieldForecast: vi.fn(), saveParcelRegime: vi.fn(), navigateTo: vi.fn(),
}));

import { YieldForecastView } from './YieldForecastSection';
import type { YieldForecastRecord } from '../types/yieldForecast';

const r = (o: Partial<YieldForecastRecord>): YieldForecastRecord => ({ status: 'done', refreshing: false, ...o });
const html = (rec: YieldForecastRecord | null, loading = false) => renderToStaticMarkup(
  <YieldForecastView parcelId="p1" record={rec} loading={loading} onRefresh={() => {}} onRegime={() => {}} />);

describe('YieldForecastView', () => {
  it('loading', () => expect(html(null, true)).toContain('yieldForecast.loading'));
  it('not computed offers refresh', () => {
    const h = html(r({ status: 'not_computed' }));
    expect(h).toContain('yieldForecast.notComputed');
    expect(h).toContain('yieldForecast.refresh');
  });
  it('done: one row per provider, experimental labelled, detail link', () => {
    const h = html(r({ estimates: [
      { provider_id: 'aquacrop', basis: 'gap_corrected', range: { low: 3, high: 4 }, validation: { status: 'experimental' } },
      { provider_id: 'newmodel', basis: 'potential', percentiles: { p10: 5, p50: 6, p90: 7 }, validation: { status: 'validated' } },
    ], computed_at: '2026-10-14T05:00:00Z' }));
    expect(h).toContain('yieldForecast.validation.experimental');
    expect(h).toContain('yieldForecast.provider.generic');  // unknown provider still shown
    expect(h).toContain('yieldForecast.detail');
  });
  it('unvalidated estimate shows its badge and each note once', () => {
    const h = html(r({
      estimates: [{ provider_id: 'aquacrop', basis: 'water_limited', percentiles: { p10: 3, p50: 4, p90: 5 },
        validation: { status: 'unvalidated' } }],
      season: { status: 'in_season', as_of: '2026-10-14', crop: 'TRZDU', regime: 'irrigated',
        sowing: { date: '2026-03-01', source: 's', provenance: 'actual' } },
    }));
    expect(h).toContain('yieldForecast.validation.unvalidated');
    for (const k of ['ceiling', 'irrigated', 'durum']) {
      expect(h.split(`yieldForecast.unvalidatedNote.${k}`).length - 1).toBe(1);
    }
  });
  it('an experimental estimate carries the measured-skill note, once', () => {
    const h = html(r({ estimates: [
      { provider_id: 'aquacrop', basis: 'gap_corrected', range: { low: 3, high: 4 }, validation: { status: 'experimental' } },
      { provider_id: 'aquacrop', basis: 'water_limited', percentiles: { p10: 5, p50: 6, p90: 7 }, validation: { status: 'not_applicable' } }] }));
    expect(h.split('yieldForecast.experimentalNote').length - 1).toBe(1);
  });
  it('validated, ceiling-only and unvalidated estimates carry no measured-skill note', () => {
    const validated = html(r({ estimates: [
      { provider_id: 'aquacrop', basis: 'gap_corrected', range: { low: 3, high: 4 }, validation: { status: 'validated' } }] }));
    const unvalidated = html(r({ estimates: [
      { provider_id: 'aquacrop', basis: 'water_limited', percentiles: { p10: 5, p50: 6, p90: 7 }, validation: { status: 'unvalidated' } }] }));
    expect(validated).not.toContain('yieldForecast.experimentalNote');
    expect(unvalidated).not.toContain('yieldForecast.experimentalNote');
  });
  it('validated and not_applicable estimates show no unvalidated badge or note', () => {
    const h = html(r({ estimates: [
      { provider_id: 'aquacrop', basis: 'gap_corrected', range: { low: 3, high: 4 }, validation: { status: 'experimental' } },
      { provider_id: 'aquacrop', basis: 'water_limited', range: { low: 5, high: 6 }, validation: { status: 'not_applicable' } }] }));
    expect(h).not.toContain('yieldForecast.validation.unvalidated');
    expect(h).not.toContain('yieldForecast.unvalidatedNote');
  });
  it('unavailable no_regime asks the regime', () => {
    const h = html(r({ status: 'unavailable', reason: 'no_regime' }));
    expect(h).toContain('yieldForecast.askRegime');
    expect(h).toContain('yieldForecast.rainfed');
  });
  it('unknown reason falls back to generic', () => {
    expect(html(r({ status: 'unavailable', reason: 'brand_new' }))).toContain('yieldForecast.reason.generic');
  });
  it('season ended keeps the estimates', () => {
    const h = html(r({ status: 'season_ended', estimates: [
      { provider_id: 'aquacrop', basis: 'gap_corrected', range: { low: 3, high: 4 }, validation: { status: 'validated' } }] }));
    expect(h).toContain('yieldForecast.seasonEnded');
    expect(h).toContain('yieldForecast.validation.validated');
  });
  it('failed shows code and refresh', () => {
    const h = html(r({ status: 'failed', code: '503' }));
    expect(h).toContain('yieldForecast.failed');
    expect(h).toContain('yieldForecast.refresh');
  });
  it('refreshing keeps content and says so', () => {
    expect(html(r({ refreshing: true, estimates: [] }))).toContain('yieldForecast.refreshing');
  });
  it('done without a visible figure still says why', () => {
    const h = html(r({ estimates: [], unavailable: [{ provider_id: 'aquacrop', reason: 'expected_missing' }] }));
    expect(h).toContain('yieldForecast.reason.expected_missing');
  });
  it('unavailable renders a single line with the localised reason', () => {
    const h = html(r({ status: 'unavailable', reason: 'not_sown' })).replace(/&quot;/g, '"');
    expect(h).toContain('yieldForecast.none:{"reason":"yieldForecast.reason.not_sown');
    expect((h.match(/<p /g) ?? []).length).toBe(1);
  });
  const normal = { provider_id: 'provincial_normal', basis: 'provincial_normal', range: { low: 2.1, high: 4.5 },
    percentiles: { p10: 2.1, p50: 3.3, p90: 4.5 }, validation: { status: 'validated' } };
  it('unavailable with a normal renders its row, the note and the reason', () => {
    const h = html(r({ status: 'unavailable', reason: 'no_regime', estimates: [normal] }));
    expect(h).toContain('yieldForecast.provider.provincial_normal');
    expect(h).toContain('yieldForecast.basis.provincial_normal');
    expect(h).toContain('yieldForecast.normalNote');
    expect(h).toContain('yieldForecast.none');
    expect(h).toContain('yieldForecast.askRegime');
  });
  it('failed with a normal renders its row and the failure line', () => {
    const h = html(r({ status: 'failed', code: 'x', estimates: [normal] }));
    expect(h).toContain('yieldForecast.basis.provincial_normal');
    expect(h).toContain('yieldForecast.failed');
    expect(h).toContain('yieldForecast.refresh');
  });
  it('unavailable without estimates shows no row and no normal note', () => {
    const h = html(r({ status: 'unavailable', reason: 'no_regime' }));
    expect(h).not.toContain('yieldForecast.provider.');
    expect(h).not.toContain('yieldForecast.normalNote');
  });
  it('done: normal row first (received order), note once', () => {
    const h = html(r({ estimates: [normal,
      { provider_id: 'aquacrop', basis: 'gap_corrected', range: { low: 3, high: 4 }, validation: { status: 'experimental' } }] }));
    expect(h.indexOf('yieldForecast.basis.provincial_normal')).toBeLessThan(h.indexOf('yieldForecast.basis.gap_corrected'));
    expect(h.split('yieldForecast.normalNote').length - 1).toBe(1);
  });
  it('no normal note without a normal row', () => {
    const h = html(r({ estimates: [{ provider_id: 'aquacrop', basis: 'gap_corrected', range: { low: 3, high: 4 }, validation: { status: 'experimental' } }] }));
    expect(h).not.toContain('yieldForecast.normalNote');
  });
});
