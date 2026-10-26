import { describe, expect, it, vi } from 'vitest';
import { parcelOnlyLabel, readZoneFromLocation, zoneEmphasis, zoneFillAlpha, zoneKey, zoneLabelStyle, zoneLabelText, zoneMapLabel, zoneNumbers, zoneOutlineStyle, zoneSelection, pinnedZoneExists, zoneViewerPath } from './zones';

const sq = (lon: number, lat: number) => ({ type: 'Polygon', coordinates: [[[lon, lat], [lon + 0.001, lat],
  [lon + 0.001, lat + 0.001], [lon, lat + 0.001], [lon, lat]]] });
const z = (parcelId: string, zoneId: string, lon?: number, lat?: number) =>
  ({ parcelId, zoneId, geometry: lon == null ? undefined : sq(lon, lat!) }) as never;

describe('zoneNumbers', () => {
  const zones = [z('p1', 'b-south-east', -1.0, 42.0), z('p1', 'a-north-west', -1.01, 42.01),
    z('p1', 'c-north-east', -1.0, 42.01), z('p2', 'x', -2, 40), z('p1', 'nogeo')];
  const n = zoneNumbers(zones);
  it('numbers each parcel from north to south, then west to east', () => {
    expect(n.get(zoneKey('p1', 'a-north-west'))).toBe(1);
    expect(n.get(zoneKey('p1', 'c-north-east'))).toBe(2);
    expect(n.get(zoneKey('p1', 'b-south-east'))).toBe(3);
  });
  it('restarts per parcel and puts zones without geometry last', () => {
    expect(n.get(zoneKey('p2', 'x'))).toBe(1);
    expect(n.get(zoneKey('p1', 'nogeo'))).toBe(4);
  });
  it('does not depend on the order the zones arrive in', () => {
    expect([...zoneNumbers([...zones].reverse()).entries()].sort()).toEqual([...n.entries()].sort());
  });
});

describe('zoneMapLabel', () => {
  it('shows number and value, or just the value', () => {
    expect(zoneMapLabel(2, 'M')).toBe('2 · M');
    expect(zoneMapLabel(undefined, 'M')).toBe('M');
  });
});

describe('zoneSelection', () => {
  it('notifies on change, toggles a pinned zone off, and clears the hover', () => {
    const seen = vi.fn();
    const off = zoneSelection.subscribe(seen);
    zoneSelection.hover({ parcelId: 'p1', zoneId: 'a' });
    expect(zoneSelection.get()).toEqual({ parcelId: 'p1', zoneId: 'a' });
    zoneSelection.hover(null);
    expect(zoneSelection.get()).toBeNull();
    zoneSelection.pin({ parcelId: 'p1', zoneId: 'a' });
    zoneSelection.hover(null);
    expect(zoneSelection.get()).toEqual({ parcelId: 'p1', zoneId: 'a' });
    zoneSelection.pin({ parcelId: 'p1', zoneId: 'a' });
    expect(zoneSelection.get()).toBeNull();
    expect(seen).toHaveBeenCalled();
    off();
  });
});

describe('zoneEmphasis', () => {
  it('lights the chosen zone, dims its siblings, leaves other parcels alone', () => {
    const sel = { parcelId: 'p1', zoneId: 'a' };
    expect(zoneEmphasis(sel, 'p1', 'a')).toBe('selected');
    expect(zoneEmphasis(sel, 'p1', 'b')).toBe('dimmed');
    expect(zoneEmphasis(sel, 'p2', 'a')).toBe('normal');
    expect(zoneEmphasis(null, 'p1', 'a')).toBe('normal');
  });
});

import { emphasisStyle } from './zones';

describe('emphasisStyle', () => {
  it('makes the chosen zone stand out and fades its siblings', () => {
    expect(emphasisStyle('normal', 0.4)).toEqual({ fillAlpha: 0.4, outlineWhite: false, outlineAlpha: 1, labelAlpha: 1, bold: false });
    expect(emphasisStyle('selected', 0.4)).toEqual({ fillAlpha: 0.75, outlineWhite: true, outlineAlpha: 1, labelAlpha: 1, bold: true });
    const dim = emphasisStyle('dimmed', 0.4);
    expect(dim.fillAlpha).toBeLessThan(0.4);
    expect(dim.labelAlpha).toBeLessThan(1);
    expect(dim.bold).toBe(false);
  });
});

import { splitZones, zoneNumberList } from './zones';

describe('zoneNumberList', () => {
  it('compacts consecutive runs and keeps singles', () => {
    expect(zoneNumberList([{ parcelId: 'p', zoneId: 'a' }], new Map([['p|a', 3]]))).toBe('3');
    const zs = ['a', 'b', 'c', 'd', 'e', 'f'].map((zoneId) => ({ parcelId: 'p', zoneId }));
    const nums = new Map([['p|a', 7], ['p|b', 1], ['p|c', 5], ['p|d', 2], ['p|e', 4], ['p|f', 6]]);
    expect(zoneNumberList(zs, nums)).toBe('1-2, 4-7');
    expect(zoneNumberList([zs[1], zs[3], zs[4]], nums)).toBe('1-2, 4');
    expect(zoneNumberList([zs[1], zs[2]], nums)).toBe('1, 5');
  });
});

describe('splitZones', () => {
  it('separates zones that differ from the parcel', () => {
    const a = { zoneId: 'a', differsFromParcel: true } as never;
    const b = { zoneId: 'b', differsFromParcel: false } as never;
    const c = { zoneId: 'c' } as never;
    const { differing, rest } = splitZones([a, b, c]);
    expect(differing).toEqual([a]);
    expect(rest).toEqual([b, c]);
  });
});

describe('map paint helpers', () => {
  it('fills only the zones that differ from the parcel', () => {
    expect(zoneFillAlpha({ differsFromParcel: false }, 0.55)).toBe(0.1);
    expect(zoneFillAlpha({ differsFromParcel: true }, 0.55)).toBe(0.55);
  });
  it('labels with the number only', () => {
    expect(zoneLabelText(3)).toBe('3');
    expect(zoneLabelText(undefined)).toBe('');
  });
  it('makes the selected label larger and shrinks labels with distance', () => {
    expect(zoneLabelStyle('normal').font).toBe('bold 20px sans-serif');
    expect(zoneLabelStyle('dimmed').font).toBe('bold 20px sans-serif');
    expect(zoneLabelStyle('selected').font).toBe('bold 24px sans-serif');
    expect(zoneLabelStyle('normal').scaleByDistance).toEqual([500, 1.0, 5000, 0.5]);
  });
  it('detects a parcel where no zone differs', () => {
    expect(parcelOnlyLabel([{ differsFromParcel: false }, { differsFromParcel: false }] as never)).toBe(true);
    expect(parcelOnlyLabel([{ differsFromParcel: false }, { differsFromParcel: true }] as never)).toBe(false);
  });
  it('reads the zone to pin from the URL', () => {
    expect(readZoneFromLocation('?parcel=p1&zone=z3')).toEqual({ parcelId: 'p1', zoneId: 'z3' });
    expect(readZoneFromLocation('?parcel=p1')).toBeNull();
    expect(readZoneFromLocation('')).toBeNull();
  });
});

describe('zoneOutlineStyle', () => {
  it('keeps the severity colour thin, whitens and thickens the selected, fades the dimmed', () => {
    expect(zoneOutlineStyle('normal', '#dc2626')).toEqual({ colorHex: '#dc2626', alpha: 1, width: 2 });
    expect(zoneOutlineStyle('selected', '#dc2626')).toEqual({ colorHex: '#ffffff', alpha: 1, width: 4 });
    expect(zoneOutlineStyle('dimmed', '#dc2626')).toEqual({ colorHex: '#dc2626', alpha: 0.4, width: 2 });
  });
});

describe('pinnedZoneExists', () => {
  const zs = [{ parcelId: 'p1', zoneId: 'a' }, { parcelId: 'p2', zoneId: 'b' }];
  it('is true for a loaded zone and for no pin', () => {
    expect(pinnedZoneExists({ parcelId: 'p1', zoneId: 'a' }, zs)).toBe(true);
    expect(pinnedZoneExists(null, zs)).toBe(true);
  });
  it('is false for a zone that is gone or belongs to another parcel', () => {
    expect(pinnedZoneExists({ parcelId: 'p1', zoneId: 'gone' }, zs)).toBe(false);
    expect(pinnedZoneExists({ parcelId: 'p1', zoneId: 'b' }, zs)).toBe(false);
    expect(pinnedZoneExists({ parcelId: 'p1', zoneId: 'a' }, [])).toBe(false);
  });
});

describe('zoneViewerPath', () => {
  it('points at the host viewer route with both ids encoded', () => {
    expect(zoneViewerPath({ parcelId: 'urn:p 1', zoneId: 'a/b' })).toBe('/entities?parcel=urn%3Ap%201&zone=a%2Fb');
  });
});
