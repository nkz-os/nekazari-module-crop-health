import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const t = (k: string, o?: unknown) => (o && typeof o === 'object' ? `${k}:${JSON.stringify(o)}` : k);
vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t, i18n: { language: 'es' } }),
}));
vi.mock('../api/cropHealthApi', () => ({
  cropHealthFetch: vi.fn(), authHeaders: () => ({}), CROP_CONTEXT_URL: 'x', navigateTo: vi.fn(),
}));

import { CropStatusSnapshotView, NoAssessmentView } from './CropStatusSnapshot';

const assessment = {
  overallSeverity: 'HIGH', recommendedAction: 'IRRIGATE_IMMEDIATE', cwsiValue: 0.5, waterStressLevel: 'moderate',
  assessedAt: '2026-10-25T08:00:00Z',
} as never;
const job = { kind: 'irrigate', when: 'today', detail: {} } as never;

const render = (extra: Record<string, unknown> = {}) => renderToStaticMarkup(
  <CropStatusSnapshotView
    parcelName="Acme North"
    assessment={assessment}
    cropCtx={null}
    nextJob={job}
    surprise={null}
    freshness="fresh"
    {...extra}
  />,
).replace(/&quot;/g, '"');

describe('CropStatusSnapshotView', () => {
  it('leads with the job, before the chips', () => {
    const h = render();
    expect(h).toContain('worklist.job.irrigate');
    expect(h.indexOf('worklist.job.irrigate')).toBeLessThan(h.indexOf('waterStress.level.moderate'));
  });
  it('shows the surprise as the justification when there is one', () => {
    const h = render({ surprise: { code: 'water_drop', detail: {} } });
    expect(h).toContain('worklist.surprise.water_drop');
  });
  it('uses the danger tone for a stale age and muted for a fresh one', () => {
    expect(render({ freshness: 'stale' })).toContain('text-nkz-danger');
    expect(render({ freshness: 'aging' })).toContain('text-nkz-warning');
    expect(render({ freshness: 'fresh' })).toContain('text-xs mt-0.5 text-nkz-text-muted');
  });
  it('still renders the header of a stale active parcel, in the danger tone', () => {
    const h = render({ freshness: 'stale' });
    expect(h).toContain('worklist.job.irrigate');
    expect(h).toContain('text-xs mt-0.5 text-nkz-danger');
  });
});

describe('water stress indicator', () => {
  const lvl = (extra: Record<string, unknown>) => render({ assessment: { ...(assessment as object), waterStressLevel: undefined, ...extra } });
  it('shows the phrase of the resolved level', () => {
    expect(lvl({ waterStressLevel: 'moderate' })).toContain('waterStress.level.moderate');
  });
  it('never renders the none phrase for no_data or an assessment without a level', () => {
    expect(lvl({ waterStressLevel: 'no_data', cwsiValue: 0.05 })).not.toContain('waterStress.level.none');
    const old = lvl({});
    expect(old).not.toContain('waterStress.level.none');
    expect(old).toContain('waterStress.level.no_data');
  });
  it('shows the rdi note only with the note flag', () => {
    expect(lvl({ waterStressLevel: 'mild', waterStressPhaseNote: 'rdi' })).toContain('waterStress.note.rdi');
    expect(lvl({ waterStressLevel: 'mild' })).not.toContain('waterStress.note.rdi');
  });
  it('shows no number for the level', () => {
    expect(lvl({ waterStressLevel: 'high', cwsiValue: 0.77 })).not.toContain('0.77');
  });
  it('shows the deficit chip neutral, never red, in a stage that needs no water', () => {
    const chip = (h: string) => (h.match(/<span class="([^"]*)">💧 20\.0mm deficit<\/span>/) ?? [])[1] ?? '';
    const neutral = chip(lvl({ waterStressLevel: 'not_needed', waterBalanceDeficit: -20 }));
    expect(neutral).toContain('text-nkz-text-secondary');
    expect(neutral).not.toContain('danger');
    expect(neutral).not.toContain('warning');
    // the millimetres are data: amber whatever their size, the level chip carries the alarm
    expect(chip(lvl({ waterStressLevel: 'high', waterBalanceDeficit: -20 }))).toContain('text-nkz-warning-strong');
  });
});

describe('header job text', () => {
  it('says nothing pending for an undated none_until, and the date for a dated one', () => {
    expect(render({ nextJob: { kind: 'none_until', when: null, detail: {} } })).toContain('worklist.job.none');
    expect(render({ nextJob: null })).toContain('worklist.job.none');
    const h = render({ nextJob: { kind: 'none_until', when: '2026-12-01', detail: { date: '2026-12-01' } } });
    expect(h).toContain('worklist.job.none_until:{"date":"');
  });
  it('scheduled irrigation uses the scheduled action text', () => {
    expect(render({ nextJob: { kind: 'irrigate', when: 'today', detail: { scheduled: true } } })).toContain('action.irrigateScheduled');
  });
});

describe('NoAssessmentView', () => {
  const r = (nextJob: unknown) => renderToStaticMarkup(<NoAssessmentView nextJob={nextJob as never} />).replace(/&quot;/g, '"');
  it('shows the job above the no-data hint', () => {
    const h = r({ kind: 'irrigate', when: 'today', detail: {} });
    expect(h).toContain('worklist.job.irrigate');
    expect(h.indexOf('worklist.job.irrigate')).toBeLessThan(h.indexOf('summary.noDataHint'));
  });
  it('shows only the hint without a job', () => {
    expect(r(null)).not.toContain('worklist.job');
  });
});

// Shape of `map_entity_to_assessment` for a zonal rollup (backend/tests/test_assessment_mapper_zones.py).
const mappedRollup = {
  id: 'urn:ngsi-ld:CropHealthAssessment:acme:p1', parcelId: 'p1',
  overallSeverity: 'HIGH', recommendedAction: 'IRRIGATE_IMMEDIATE', cwsiValue: 0.5,
  assessedAt: '2026-10-25T08:00:00Z',
  worstZoneRank: 3, worstZoneId: 'z3', zoneSpread: 12.5,
};

describe('CropStatusSnapshotView worst zone', () => {
  const view = (a: object) => renderToStaticMarkup(
    <CropStatusSnapshotView assessment={a as never} cropCtx={null} nextJob={job} surprise={null} freshness="fresh" />,
  ).replace(/&quot;/g, '"');
  it('names the worst zone of a mapped zonal rollup', () => {
    expect(view(mappedRollup)).toContain('zones.worst:{"n":3}');
  });
  it('shows nothing when the mapper left the rank null', () => {
    expect(view({ ...mappedRollup, worstZoneRank: null, worstZoneId: null, zoneSpread: null })).not.toContain('zones.worst');
  });
});

describe('rainfed parcel', () => {
  const dry = (extra: Record<string, unknown> = {}) => render({
    nextJob: null,
    assessment: {
      ...(assessment as object), irrigationRegime: 'rainfed', overallSeverity: 'MEDIUM',
      recommendedAction: 'MONITOR', waterStressLevel: 'high', waterBalanceDeficit: -22.9,
      soilWaterBalance: { stressLevel: 'high', swMm: 16, awcMm: 39, swRatio: 0.42 },
      ...extra,
    },
  });
  it('names the level as how dry it is and gives no irrigation task', () => {
    const h = dry();
    expect(h).toContain('waterStress.rainfed.high');
    expect(h).not.toContain('waterStress.level.high');
    expect(h).toContain('action.monitor');
    expect(h).not.toContain('irrigate');
  });
  it('words the soil reserve without an irrigation instruction', () => {
    const h = dry();
    expect(h).toContain('soil.reservoirRainfed.high');
    expect(h).not.toContain('soil.reservoir.high');
  });
  it('is amber, and red only when the severity was raised', () => {
    expect(dry()).not.toContain('bg-nkz-danger-soft');
    expect(dry({ overallSeverity: 'HIGH' })).toContain('bg-nkz-danger-soft');
  });
  it('an irrigated parcel keeps the usual wording, with the millimetres in amber', () => {
    const h = dry({ irrigationRegime: 'irrigated', overallSeverity: 'CRITICAL', recommendedAction: 'IRRIGATE_IMMEDIATE' });
    expect(h).toContain('waterStress.level.high');
    expect(h).toContain('soil.reservoir.high');
    expect(h).toContain('action.irrigateImmediate');
  });
});
