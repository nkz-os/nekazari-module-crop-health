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
});
