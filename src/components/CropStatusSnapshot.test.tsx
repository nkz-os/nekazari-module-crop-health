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

import { CropStatusSnapshotView } from './CropStatusSnapshot';

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
    stale={false}
    {...extra}
  />,
).replace(/&quot;/g, '"');

describe('CropStatusSnapshotView', () => {
  it('leads with the job, before the chips', () => {
    const h = render();
    expect(h).toContain('worklist.job.irrigate');
    expect(h).toContain('worklist.when.today');
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
  it('renders nothing of the assessment when stale', () => {
    expect(render({ stale: true })).toBe('');
  });
});
