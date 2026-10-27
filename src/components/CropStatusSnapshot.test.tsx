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
  overallSeverity: 'HIGH', recommendedAction: 'IRRIGATE_IMMEDIATE', cwsiValue: 0.5,
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
    expect(h.indexOf('worklist.job.irrigate')).toBeLessThan(h.indexOf('summary.cwsi.moderate'));
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

describe('CropStatusSnapshotView worst zone', () => {
  const view = (a: object) => renderToStaticMarkup(
    <CropStatusSnapshotView assessment={{ ...(assessment as object), ...a } as never} cropCtx={null} nextJob={job} surprise={null} freshness="fresh" />,
  ).replace(/&quot;/g, '"');
  it('names the worst zone when the assessment carries its rank', () => {
    expect(view({ worstZoneRank: 3 })).toContain('zones.worst:{"n":3}');
  });
  it('shows nothing without it', () => {
    expect(view({})).not.toContain('zones.worst');
  });
});
