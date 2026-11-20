import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t: (k: string, o?: any) => (o ? `${k}:${JSON.stringify(o)}` : k), i18n: { language: 'es' } }),
}));
vi.mock('../api/cropHealthApi', () => ({ getWaterLoss: vi.fn() }));

import { WaterLossView } from './WaterLossSection';
import type { PollSnapshot } from './waterLossModel';
import type { WaterLossResponse, WaterLossStage } from '../types/waterLoss';

const stage = (o: Partial<WaterLossStage>): WaterLossStage => ({
  index: 0, key: 'establishment', start: '2026-01-01', end: '2026-02-01', state: 'complete',
  milestones: null, milestones_reason: null, gain_t_ha_model: null, gain_pct_of_potential: null, end_in_relief_run: null, ...o,
});
const done = (o: Partial<WaterLossResponse> = {}, status: 'in_season' | 'complete' = 'complete'): WaterLossResponse => ({
  contract_version: '2.11', provider_id: 'aquacrop_water_loss', state: 'done', done: 1, total: 1, job_id: null, unavailable: [],
  season: { status, as_of: '2026-05-01', crop: 'TRZAX', regime: 'rainfed', sowing: { date: '2025-11-01', source: 'crop_cycle', provenance: 'actual' },
    n_years: 10, ensemble: null, cycle: status === 'complete' ? 'previous' : 'current', harvest_recorded: '2026-07-10', computed_at: null, provider_version: 'x' },
  result: {
    total: { water_gap_pct: 23, water_gap_band: null, water_limited_t_ha: 5.5, potential_t_ha: 7.1 },
    stages: [
      stage({ index: 0, key: 'establishment', gain_pct_of_potential: 12, gain_t_ha_model: 0.987 }),
      stage({ index: 1, key: 'canopy_growth', state: 'complete', gain_pct_of_potential: 4 }),
      stage({ index: 2, key: 'max_canopy', state: 'in_progress', start: '2026-04-01', end: null }),
      stage({ index: 3, key: 'senescence', state: 'not_reached', start: null, end: null }),
    ],
    stage_bounds_basis: 'rainfed_simulation', milestones_basis: 'thermal_time_no_stress_delay',
    yield_basis: { moisture: 'dry' }, validation: { status: 'validated_forecast_crop', note: 'English api text' },
    label: 'API LABEL', notes: ['API NOTE'], sources: [{ short: 'Src A', detail: 'Detail A' }], engine_version: 'e', warnings: [],
  },
  ...o,
});
const html = (snap: PollSnapshot) => renderToStaticMarkup(<WaterLossView snap={snap} onRetry={() => {}} onRecheck={() => {}} />);

describe('WaterLossView', () => {
  it('loading and polling show the computing text', () => {
    expect(html({ phase: 'loading', data: null })).toContain('waterLoss.computing');
    expect(html({ phase: 'polling', data: { ...done(), state: 'running', result: null } })).toContain('waterLoss.computing');
  });
  it('done renders four stage rows with state labels and P50 for the complete stage', () => {
    const h = html({ phase: 'settled', data: done() });
    for (const k of ['establishment', 'canopy_growth', 'max_canopy', 'senescence']) expect(h).toContain(`waterLoss.stage.${k}`);
    for (const s of ['complete', 'in_progress', 'not_reached']) expect(h).toContain(`waterLoss.state.${s}`);
    expect(h).toContain('waterLoss.modelEstimate');
    expect(h).toContain('12%');
    expect(h).toContain('waterLoss.sourcesTitle');
    expect(h).toContain('Src A');
  });
  it('previous-cycle header shows the harvest date', () => {
    const h = html({ phase: 'settled', data: done() });
    expect(h).toContain('waterLoss.cycle.complete');
    expect(h).toContain('harvest');
    expect(h).not.toContain('waterLoss.notes.changesUntilHarvest');
  });
  it('in-season header shows as_of, bands and the changes-until-harvest note', () => {
    const d = done({}, 'in_season');
    d.result!.total = { water_gap_pct: 20, water_gap_band: { p10: 10, p50: 20, p90: 30 }, water_limited_t_ha: null, potential_t_ha: null };
    d.result!.stages[0].gain_pct_of_potential = { p10: 5, p50: 8, p90: 11 };
    const h = html({ phase: 'settled', data: d });
    expect(h).toContain('waterLoss.cycle.in_season');
    expect(h).toContain('asOf');
    expect(h).toContain('waterLoss.notes.changesUntilHarvest');
    expect(h).toContain('&quot;low&quot;:&quot;10&quot;');
    expect(h).toContain('&quot;high&quot;:&quot;11&quot;');
  });
  it('validation text follows validation.status, not the API note', () => {
    expect(html({ phase: 'settled', data: done() })).toContain('waterLoss.validation.validated_forecast_crop');
    const d = done(); d.result!.validation.status = 'unvalidated';
    const h = html({ phase: 'settled', data: d });
    expect(h).toContain('waterLoss.validation.unvalidated');
    expect(h).not.toContain('English api text');
    expect(h).not.toContain('API NOTE');
    expect(h).not.toContain('API LABEL');
  });
  it('static notes: non-additive and flowering', () => {
    const h = html({ phase: 'settled', data: done() });
    expect(h).toContain('waterLoss.notes.notAdditive');
    expect(h).toContain('waterLoss.notes.flowering');
  });
  it('unavailable shows translated reason; unknown reason falls to other', () => {
    const u = (reason: string) => html({ phase: 'settled', data: { ...done(), state: 'unavailable', result: null, season: null, unavailable: [{ provider_id: 'aquacrop', reason }] } });
    expect(u('not_sown')).toContain('waterLoss.reason.not_sown');
    const h = u('weird_x');
    expect(h).toContain('waterLoss.reason.other');
    expect(h).not.toContain('weird_x');
  });
  it('failed and error show the retry button', () => {
    expect(html({ phase: 'settled', data: { ...done(), state: 'failed', result: null, season: null } })).toContain('waterLoss.retry');
    expect(html({ phase: 'error', data: null })).toContain('waterLoss.retry');
  });
  it('timeout shows the still-computing message and a check-again button', () => {
    const h = html({ phase: 'timeout', data: { ...done(), state: 'running', result: null } });
    expect(h).toContain('waterLoss.stillComputing');
    expect(h).toContain('waterLoss.checkAgain');
  });
  it('never shows t/ha', () => {
    const h = html({ phase: 'settled', data: done() });
    expect(h).not.toMatch(/t\/ha|t_ha|0\.987|5\.5|7\.1/);
  });
});
