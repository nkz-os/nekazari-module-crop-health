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
  cropStatus: 'active', assessedAt: new Date().toISOString(), nextJob: null, surprise: null,
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
    expect(html).toContain('worklist.when.today');
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
