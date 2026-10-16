import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t: (k: string, o?: unknown) => (o && typeof o === 'object' ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import ZoneHealthPanel from './ZoneHealthPanel';

const sq = (lon: number, lat: number) => ({ type: 'Polygon', coordinates: [[[lon, lat], [lon + 0.001, lat],
  [lon + 0.001, lat + 0.001], [lon, lat + 0.001], [lon, lat]]] });
const zone = (zoneId: string, lat: number) => ({ parcelId: 'p1', zoneId, geometry: sq(-1, lat),
  overallSeverity: 'LOW', cwsiValue: 0.2 }) as never;

describe('ZoneHealthPanel', () => {
  const html = renderToStaticMarkup(<ZoneHealthPanel zones={[zone("south", 42.0), zone("north", 42.01)]} isWholeParcel={false} />).replace(/&quot;/g, "\"");
  it('names zones by their map number, in map order', () => {
    expect(html.indexOf('zones.zoneLabel:{"id":1}')).toBeGreaterThan(-1);
    expect(html.indexOf('zones.zoneLabel:{"id":1}')).toBeLessThan(html.indexOf('zones.zoneLabel:{"id":2}'));
    expect(html).not.toContain('zones.zoneLabel:{"id":"south"}');
  });
  it('rows are buttons that say how to find the zone on the map', () => {
    expect(html.match(/<button[^>]*aria-pressed="false"/g)?.length).toBe(2);
    expect(html).toContain('zones.selectHint');
  });
});
