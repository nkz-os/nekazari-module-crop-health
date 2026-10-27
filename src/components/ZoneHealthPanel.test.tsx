import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t: (k: string, o?: unknown) => (o && typeof o === 'object' ? `${k}:${JSON.stringify(o)}` : k) }),
}));

vi.mock('../api/cropHealthApi', () => ({ navigateTo: vi.fn() }));

import ZoneHealthPanel from './ZoneHealthPanel';
import { zoneNumbers } from '../utils/zones';

const sq = (lon: number, lat: number) => ({ type: 'Polygon', coordinates: [[[lon, lat], [lon + 0.001, lat],
  [lon + 0.001, lat + 0.001], [lon, lat + 0.001], [lon, lat]]] });
const zone = (zoneId: string, lat: number, differsFromParcel = true) => ({ parcelId: 'p1', zoneId, geometry: sq(-1, lat),
  overallSeverity: 'LOW', cwsiValue: 0.2, differsFromParcel }) as never;
const pv = { cwsiValue: 0.5 };
const render = (zones: never[], whole = false) =>
  renderToStaticMarkup(<ZoneHealthPanel zones={zones} isWholeParcel={whole} parcelValues={pv} />).replace(/&quot;/g, '"');

describe('ZoneHealthPanel', () => {
  const html = render([zone('south', 42.0), zone('north', 42.01)]);
  it('names zones by their map number, in map order', () => {
    expect(html.indexOf('zones.zoneLabel:{"id":1}')).toBeGreaterThan(-1);
    expect(html.indexOf('zones.zoneLabel:{"id":1}')).toBeLessThan(html.indexOf('zones.zoneLabel:{"id":2}'));
    expect(html).not.toContain('zones.zoneLabel:{"id":"south"}');
  });
  it('shows the composite index on its own 0-100 scale', () => {
    const composite = { parcelId: 'p1', zoneId: 'c', geometry: sq(-1, 42), overallSeverity: 'CRITICAL',
      compositeStressIndex: 66.7 } as never;
    const out = renderToStaticMarkup(<ZoneHealthPanel zones={[{ ...(composite as object), differsFromParcel: true }] as never[]} isWholeParcel={false} parcelValues={{ compositeStressIndex: 10 }} />);
    expect(out).toContain('67%');
    expect(out).not.toContain('6670%');
  });
  it('each differing row has a show-on-map button and the parcel value', () => {
    expect(html.match(/zones\.showOnMap/g)?.length).toBe(2);
    expect(html).toContain('zones.parcelValue:{"value":"CWSI 0.50"}');
  });
  it('lists only the zone that differs and summarises the rest with map numbers', () => {
    const zs = [zone('a', 42.02, false), zone('b', 42.01, true), zone('c', 42.0, false)];
    const out = render(zs);
    expect(out.match(/zones\.showOnMap/g)?.length).toBe(1);
    expect(out).toContain('zones.zoneLabel:{"id":2}');
    expect(out).not.toContain('zones.zoneLabel:{"id":1}');
    expect(out).toContain('zones.rest:{"list":"1, 3"}');
    expect(zoneNumbers(zs as never).get('p1|b')).toBe(2);
  });
  it('says there is no difference when no zone differs', () => {
    const out = render([zone('a', 42.01, false), zone('b', 42.0, false)]);
    expect(out).toContain('zones.noDifference:{"count":2}');
    expect(out).not.toContain('zones.showOnMap');
    expect(out).not.toContain('zones.rest');
  });
  it('paints nothing for a whole-parcel result', () => {
    expect(render([zone('a', 42)], true)).toBe('');
  });
  it('shows per-zone input provenance and wetness', () => {
    const z1 = { ...(zone('a', 42) as object), inputFidelity: { meteo: 'zone_specific', ndvi: 'iot_sensor', soil: 'parcel_inherited', sar: 'unavailable' }, wetnessClass: 'wet' } as never;
    const out = render([z1]);
    expect(out).toContain('zones.fidelity.own: zones.fidelity.meteo · zones.fidelity.ndvi — zones.fidelity.inherited: zones.fidelity.soil');
    expect(out).toContain('zones.wetness.wet');
  });
  it('omits the provenance line when nothing is own or inherited', () => {
    expect(render([zone('a', 42)])).not.toContain('zones.fidelity.own');
  });
});
