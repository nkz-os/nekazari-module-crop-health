import { describe, expect, it, vi } from 'vitest';
import { zoneEmphasis, zoneKey, zoneMapLabel, zoneNumbers, zoneSelection } from './zones';

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
