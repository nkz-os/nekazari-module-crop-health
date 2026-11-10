import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const t = (k: string, o?: unknown) => (o && typeof o === 'object' ? `${k}:${JSON.stringify(o)}` : k);
vi.mock('@nekazari/sdk', () => ({ useTranslation: () => ({ t, i18n: { language: 'es' } }) }));
vi.mock('../api/fieldOperationsApi', () => ({ recordObservedStage: vi.fn() }));

import PhenologyTimeline from './PhenologyTimeline';
import type { PhenologyStatus } from '../types/assessment';

const render = (status: PhenologyStatus | null) =>
  renderToStaticMarkup(<PhenologyTimeline status={status} parcelId="urn:p1" onRecorded={() => {}} />)
    .replace(/&quot;/g, '"');

const LEGACY: PhenologyStatus = {
  status: 'ok', currentStage: 'vegetative', deviation: 'ahead', gdd: { accumulated: 812.4 },
  stages: [
    { stage: 'emergence', reached: true, projectedDate: '2026-11-17' },
    { stage: 'vegetative', current: true },
    { stage: 'flowering', projectedDate: '2027-04-15' },
  ],
};

const LEGACY_HTML = `<div class="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3"><div class="flex items-center justify-between mb-2"><h3 class="text-sm font-semibold text-nkz-text-primary">phenologyTimeline.title</h3><span class="text-xs text-nkz-text-muted">GDD 812</span></div><div class="flex gap-1 overflow-x-auto pb-1"><div class="min-w-[70px] flex-shrink-0 rounded-md border px-2 py-1.5 text-center border-nkz-success bg-nkz-success-soft text-nkz-success-strong"><p class="text-[11px] font-medium leading-tight">phenology.stage.emergence</p><p class="text-[10px] opacity-80 mt-0.5">11-17</p></div><div class="min-w-[70px] flex-shrink-0 rounded-md border px-2 py-1.5 text-center border-nkz-accent-base bg-nkz-accent-soft text-nkz-accent-strong"><p class="text-[11px] font-medium leading-tight">phenology.stage.vegetative</p></div><div class="min-w-[70px] flex-shrink-0 rounded-md border px-2 py-1.5 text-center border-nkz-border bg-nkz-surface text-nkz-text-muted"><p class="text-[11px] font-medium leading-tight">phenology.stage.flowering</p><p class="text-[10px] opacity-80 mt-0.5">04-15</p></div></div><p class="text-xs text-nkz-warning-strong mt-2">phenologyTimeline.deviation:{"value":"ahead"}</p></div>`;

const CEREAL: PhenologyStatus = {
  ...LEGACY,
  stages: [
    { stage: 'emergence', reached: true, bbchFrom: 0, bbchTo: 9 },
    { stage: 'vegetative', current: true, bbchFrom: 10, bbchTo: 49 },
    { stage: 'flowering', bbchFrom: 51, bbchTo: 69 },
  ],
  model: { id: 'aquacrop_calendar', cultivar: 'WheatGDD', version: '3.1.0' },
  calibration: { status: 'calibrated', region: 'Navarra', version: '2026-10-13' },
  validation: { status: 'not_validated' },
  experimental: true,
  basis: 'thermal_time',
  milestones: {
    emergence: { gdd: 150, status: 'reached', date: '2026-11-17' },
    flowering_start: { gdd: 1450, status: 'projected', date_p10: '2027-04-08', date_p50: '2027-04-15', date_p90: '2027-04-24' },
    senescence_start: { gdd: 1686, status: 'unavailable', reason: 'weather_unavailable' },
    maturity: { gdd: 2809, status: 'projected', date_p50: '2027-06-20' },
  },
  observations: [
    { date: '2027-03-02', bbch: '31', stage: 'vegetative', modelStageOnDate: 'vegetative', milestone: null, deltaDays: null },
    { date: '2027-04-20', bbch: '55', stage: 'flowering', modelStageOnDate: null, milestone: 'flowering_start', deltaDays: -5 },
    { date: '2027-04-10', bbch: '52', stage: 'flowering', modelStageOnDate: 'vegetative', milestone: 'flowering_start', deltaDays: 5 },
    { date: '2027-04-15', bbch: '53', stage: 'flowering', modelStageOnDate: 'flowering', milestone: 'flowering_start', deltaDays: 0 },
  ],
};

describe('PhenologyTimeline', () => {
  it('renders nothing without stages or while pending', () => {
    expect(render(null)).toBe('');
    expect(render({ status: 'pending' })).toBe('');
  });

  it('renders exactly as before for a status without the calendar fields', () => {
    expect(render(LEGACY)).toBe(LEGACY_HTML);
  });

  it('shows the experimental badge, model and calibration region', () => {
    const h = render(CEREAL);
    expect(h).toContain('phenologyTimeline.experimental');
    expect(h).toContain('phenologyTimeline.modelCalibrated:{"model":"WheatGDD 3.1.0","region":"Navarra"}');
  });

  it('names the model without a region when not calibrated', () => {
    const h = render({ ...CEREAL, calibration: { status: 'builtin' } });
    expect(h).toContain('phenologyTimeline.model:{"model":"WheatGDD 3.1.0"}');
    expect(h).not.toContain('modelCalibrated');
  });

  it('shows the BBCH range of each stage', () => {
    const h = render(CEREAL);
    expect(h).toContain('phenologyTimeline.bbchRange:{"from":0,"to":9}');
    expect(h).toContain('phenologyTimeline.bbchRange:{"from":51,"to":69}');
  });

  it('shows a single BBCH code for a stage that is one code wide', () => {
    const h = render({ ...CEREAL, stages: [...CEREAL.stages!, { stage: 'maturity', bbchFrom: 89, bbchTo: 89 }] });
    expect(h).toContain('phenologyTimeline.bbchSingle:{"code":89}');
    expect(h).not.toContain('"from":89');
  });

  it('shows milestone dates only as the data has them', () => {
    const h = render(CEREAL);
    expect(h).toContain('phenologyTimeline.milestoneReached:{"date":"2026-11-17"}');
    expect(h).toContain('phenologyTimeline.milestoneProjected:{"p50":"2027-04-15","p10":"2027-04-08","p90":"2027-04-24"}');
    expect(h).toContain('phenologyTimeline.milestoneProjectedNoRange:{"p50":"2027-06-20"}');
    expect(h).toContain('phenologyTimeline.milestoneUnavailable:{"reason":"weather_unavailable"}');
    expect(h).toContain('phenologyTimeline.milestone.senescence_start');
    expect(h).not.toContain('2027-06-2"'); // no invented range for maturity
  });

  it('states the thermal-time basis', () => {
    expect(render(CEREAL)).toContain('phenologyTimeline.basisThermalTime');
    expect(render({ ...CEREAL, basis: undefined })).not.toContain('basisThermalTime');
  });

  it('says not validated', () => {
    expect(render(CEREAL)).toContain('phenologyTimeline.notValidated');
  });

  const M = (n: number, bias: number, mae: number) => ({ n, bias_days: bias, mae_days: mae, p10_days: -10, p90_days: 10 });
  const MEASURED: PhenologyStatus['validation'] = {
    status: 'measured', version: '2026-11-10',
    dataset: { name: 'GENVCE per-site variety trial result sheets', country: 'ES', seasons: [2023, 2024, 2025, 2026], sheets: 303 },
    groups: {
      winter_type: { emergence: M(44, 0, 8.5), heading: M(60, -4.0, 9.6), maturity: M(10, 14.5, 12.4), harvest: M(64, -2.0, 10.9) },
      spring_type: { heading: M(55, 1.0, 5.8), harvest: M(64, -1.0, 14.2) },
    },
  };

  it('shows measured error, bias in words and n per group, heading and harvest only', () => {
    const h = render({ ...CEREAL, validation: MEASURED });
    expect(h).not.toContain('notValidated');
    expect(h).toContain('"name":"phenologyTimeline.validationGroup.heading","mae":"9.6","n":60');
    expect(h).toContain('"mae":"10.9","n":64');
    expect(h).toContain('"mae":"5.8","n":55');
    expect(h).toContain('phenologyTimeline.validationBiasEarly:{"days":"4.0"}');
    expect(h).toContain('phenologyTimeline.validationBiasEarly:{"days":"2.0"}');
    expect(h).toContain('phenologyTimeline.validationBiasLate:{"days":"1.0"}');
    expect(h).toContain('phenologyTimeline.validationBiasEarly:{"days":"1.0"}'); // spring harvest -1.0
    expect(h).not.toContain('"mae":"8.5"'); // emergence is not shown
    expect(h).not.toContain('"mae":"12.4"');
    expect(h).toContain('phenologyTimeline.validationGroupName.winter_type');
    expect(h).toContain('phenologyTimeline.validationDataset:{"name":"GENVCE per-site variety trial result sheets","seasons":"2023–2026"}');
    expect(h).toContain('phenologyTimeline.validationSheets:{"count":303}');
  });

  it('says no bias under half a day, and skips absent comparisons and empty groups', () => {
    const h = render({ ...CEREAL, validation: { status: 'measured', groups: {
      all: { harvest: M(30, 0.4, 7.0) }, other: { emergence: M(5, 1, 2) },
    } } });
    expect(h).toContain('phenologyTimeline.validationBiasNone');
    expect(h).toContain('"mae":"7.0","n":30');
    expect(h).not.toContain('validationGroup.heading');
    expect(h).not.toContain('validationGroupName.other');
    expect(h).not.toContain('validationDataset');
  });

  it('lists observations with the difference in words, never a made-up one', () => {
    const h = render(CEREAL);
    expect(h).toContain('phenologyTimeline.observations.title');
    expect(h).toContain('2027-03-02');
    expect(h).toContain('phenologyTimeline.observations.bbch:{"code":"55"}');
    expect(h).toContain('phenologyTimeline.observations.modelEarlier:{"count":5}');
    expect(h).toContain('phenologyTimeline.observations.modelLater:{"count":5}');
    expect(h).toContain('phenologyTimeline.observations.sameDay');
    expect((h.match(/observations\.(modelEarlier|modelLater|sameDay)/g) ?? []).length).toBe(3);
  });

  it('offers the form only with a model, and the BBCH attribution', () => {
    const h = render(CEREAL);
    expect(h).toContain('phenologyTimeline.form.title');
    expect(h).toContain('phenologyTimeline.bbchAttribution');
    expect(render(LEGACY)).not.toContain('form.title');
    expect(render(LEGACY)).not.toContain('bbchAttribution');
  });
});
