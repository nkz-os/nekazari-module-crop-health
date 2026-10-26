import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const t = (k: string, o?: unknown) => (o && typeof o === 'object' ? `${k}:${JSON.stringify(o)}` : k);
vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t, i18n: { language: 'es' } }),
}));
vi.mock('../api/cropHealthApi', () => ({
  cropHealthFetch: vi.fn(async () => ({ parcels: [], summary: { surprises: 0, jobsToday: 0, noData: 0 } })),
  navigateTo: vi.fn(),
}));

import { ParcelRows } from './ParcelList';
import FleetOverview from './FleetOverview';

const base = { hasData: true, freshness: 'fresh', stale: false, plannedCrop: null, lastAssessment: null } as const;
const busy = {
  ...base, parcelId: 'p1', parcelName: 'Acme North', cropName: 'Trigo', phenologyStage: 'tillering',
  cropStatus: 'active', assessedAt: new Date().toISOString(),
  nextJob: { kind: 'irrigate', when: 'today', detail: {} },
  surprise: { code: 'water_drop', detail: {} },
} as never;
const calm = {
  ...base, parcelId: 'p2', parcelName: 'Acme South', cropName: 'Cebada', phenologyStage: 'heading',
  cropStatus: 'active', assessedAt: new Date().toISOString(), nextJob: { kind: 'none_until', when: null, detail: {} }, surprise: null,
} as never;
const noCrop = {
  ...base, parcelId: 'p3', parcelName: 'Acme East', hasData: false, cropStatus: 'none', freshness: 'none',
  nextJob: { kind: 'sow', when: 'today', detail: { crop: 'Trigo duro', workability: 'optimal' } }, surprise: null,
} as never;
const pending = {
  ...base, parcelId: 'p4', parcelName: 'Acme West', hasData: false, cropStatus: 'active', freshness: 'none',
  nextJob: null, surprise: null,
} as never;

const render = (rows: unknown[]) => renderToStaticMarkup(
  <ParcelRows rows={rows as never} selectedParcelId={null} onSelect={() => {}} t={t as never} lang="es" />,
).replace(/&quot;/g, '"');

describe('ParcelRows', () => {
  it('shows job and surprise lines and keeps backend order', () => {
    const html = render([busy, calm]);
    expect(html).toContain('worklist.job.irrigate');
    expect(html).not.toContain('worklist.when.today');
    expect(html).toContain('worklist.surprise.water_drop');
    expect(html).toContain('phenology.stage.tillering');
    expect(html.indexOf('Acme North')).toBeLessThan(html.indexOf('Acme South'));
    const calmHtml = render([calm]);
    expect(calmHtml).not.toContain('worklist.job.none');
    expect(calmHtml.match(/<p /g)?.length).toBe(2);
  });
  it('no active crop shows the sow job with workability', () => {
    const html = render([noCrop]);
    expect(html).toContain('worklist.noActiveCrop');
    expect(html).toContain('worklist.job.sow:{"crop":"Trigo duro"');
    expect(html).toContain('worklist.workability.optimal');
  });
  it('active crop without assessment is pending', () => {
    expect(render([pending])).toContain('worklist.job.pending_assessment');
  });
});

const job = (nextJob: unknown, extra: Record<string, unknown> = {}) =>
  ({ ...(calm as object), nextJob, ...extra }) as never;

describe('job text', () => {
  it('shows no job line for an undated none_until', () => {
    expect(render([calm]).match(/<p /g)?.length).toBe(2);
  });
  it('none_until with a date has the date and no when suffix', () => {
    const h = render([job({ kind: 'none_until', when: '2026-12-01', detail: { date: '2026-12-01' } })]);
    expect(h).toContain('worklist.job.none_until:{"date":"');
    expect(h).not.toMatch(/none_until[^<]* · /);
  });
  it('scheduled irrigation says so, without today', () => {
    const h = render([job({ kind: 'irrigate', when: 'today', detail: { scheduled: true } })]);
    expect(h).toContain('action.irrigateScheduled');
    expect(h).not.toContain('worklist.when.today');
    expect(render([job({ kind: 'irrigate', when: 'today', detail: {} })])).toContain('worklist.job.irrigate');
  });
  it('sow without a date says no date, and uses the planned crop name', () => {
    const h = render([job({ kind: 'sow', when: null, detail: { crop: 'X', species: 'TRZAX' } },
      { plannedCrop: { species: 'TRZAX', names: { es: 'Trigo' } } })]);
    expect(h).toContain('worklist.job.sow:{"crop":"Trigo"}: worklist.when.noDate');
  });
  it('sow with a date adds workability and the date', () => {
    const h = render([job({ kind: 'sow', when: '2026-11-05', detail: { species: 'TRZAX', workability: 'too_wet' } })]);
    expect(h).toContain('"crop":"TRZAX"');
    expect(h).toContain('worklist.workability.too_wet');
    expect(h).toContain(' · ');
  });
  it('treat translates the disease code', () => {
    const h = render([job({ kind: 'treat', when: 'today', detail: { disease: 'downy_mildew' } })]);
    expect(h).toContain('worklist.job.treat:{"disease":"disease.downy_mildew:{\\"defaultValue\\":\\"downy_mildew\\"}"}');
  });
  it('harvest keeps the when suffix', () => {
    expect(render([job({ kind: 'harvest', when: '2026-07-01', detail: { date: '2026-07-01' } })])).toContain('worklist.job.harvest');
  });
});

describe('row details', () => {
  it('colours a stale age as danger and labels the dot', () => {
    const stale = { ...(calm as object), freshness: 'stale', stale: true } as never;
    const html = render([stale]);
    expect(html).toMatch(/text-nkz-danger[^>]*>relativeTime/);
    expect(html).toContain('aria-label="worklist.state.green"');
  });
});

describe('FleetOverview', () => {
  it('shows only the three counters', () => {
    const html = renderToStaticMarkup(<FleetOverview summary={{ surprises: 2, jobsToday: 5, noData: 1 }} />);
    expect(html).toContain('fleet.surprises');
    expect(html).toContain('fleet.jobsToday');
    expect(html).toContain('fleet.noData');
    expect(html).not.toContain('fleet.monitored');
    expect(html).toMatch(/>2<[\s\S]*>5<[\s\S]*>1</);
  });
});
