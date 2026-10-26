import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const t = (k: string, o?: unknown) => (o && typeof o === 'object' ? `${k}:${JSON.stringify(o)}` : k);
vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t, i18n: { language: 'es' } }),
}));
vi.mock('../api/cropHealthApi', () => ({ navigateTo: vi.fn() }));

import NoActiveCropCard from './NoActiveCropCard';

const render = (props: Record<string, unknown>) => renderToStaticMarkup(
  <NoActiveCropCard parcelId="p1" plannedCrop={null} lastAssessment={null} {...props} />,
).replace(/&quot;/g, '"');

describe('NoActiveCropCard', () => {
  it('names the planned crop and offers planning', () => {
    const h = render({ plannedCrop: { species: 'TRZAX', names: { es: 'Trigo', en: 'Wheat' } } });
    expect(h).toContain('noCrop.title');
    expect(h).toContain('noCrop.next:{"crop":"Trigo","when":"worklist.when.noDate"}');
    expect(h).toContain('noCrop.plan');
  });
  it('shows the planned sowing date when there is one', () => {
    const h = render({ plannedCrop: { species: 'TRZAX', sowingDate: '2026-11-05' } });
    expect(h).not.toContain('worklist.when.noDate');
    expect(h).toMatch(/"when":"[^"]*2026|"when":"[^"]*11/);
  });
  it('falls back to the species code without a localised name', () => {
    expect(render({ plannedCrop: { species: 'TRZAX' } })).toContain('"crop":"TRZAX"');
  });
  it('shows the last assessment when there is one, and no next line without a plan', () => {
    const h = render({ lastAssessment: { assessedAt: '2026-10-01T00:00:00Z', cropName: 'Cebada' } });
    expect(h).toContain('noCrop.last');
    expect(h).toContain('Cebada');
    expect(h).not.toContain('noCrop.next');
    expect(render({ lastAssessment: { assessedAt: '2026-10-01T00:00:00Z' } })).toContain('noCrop.lastNoCrop');
    expect(render({ plannedCrop: { species: 'TRZAX', names: { es: 'Trigo' } } })).toContain('"crop":"Trigo"');
    expect(h).toContain('noCrop.plan');
  });
});
