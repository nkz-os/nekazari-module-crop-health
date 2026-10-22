/**
 * Management zones as the user sees them: a short number per zone, the same on the map and in
 * the side panel, and the zone the user is pointing at in the panel (shared with the map layer,
 * which is another slot of this module).
 */

type Geometry = { type: string; coordinates: number[][][] | number[][][][] } | undefined;

interface ZoneLike {
  parcelId?: string | null;
  zoneId: string;
  geometry?: Geometry;
}

export function polygonRings(geometry: Geometry): number[][][] {
  if (!geometry) return [];
  if (geometry.type === 'Polygon') return geometry.coordinates as number[][][];
  if (geometry.type === 'MultiPolygon') return (geometry.coordinates as number[][][][]).map((poly) => poly[0]);
  return [];
}

export function zoneCentroid(geometry: Geometry): [number, number] | null {
  const ring = polygonRings(geometry)[0];
  if (!ring?.length) return null;
  let lon = 0;
  let lat = 0;
  for (const [x, y] of ring) {
    lon += x;
    lat += y;
  }
  return [lon / ring.length, lat / ring.length];
}

export function zoneKey(parcelId: string | null | undefined, zoneId: string): string {
  return `${parcelId ?? ''}|${zoneId}`;
}

// Centroids closer than this (degrees, about 10 m) count as the same row, so the order reads
// west to east along it instead of jumping on rounding noise.
const ROW = 1e-4;

/**
 * Zone number per parcel, 1-based, read like a page: north to south, then west to east.
 * Zones without geometry come last, by id. Independent of the order the zones arrive in.
 */
export function zoneNumbers(zones: ZoneLike[]): Map<string, number> {
  const byParcel = new Map<string, ZoneLike[]>();
  for (const z of zones) {
    const list = byParcel.get(z.parcelId ?? '') ?? [];
    list.push(z);
    byParcel.set(z.parcelId ?? '', list);
  }
  const out = new Map<string, number>();
  byParcel.forEach((list) => {
    const keyed = list.map((z) => ({ z, c: zoneCentroid(z.geometry) }));
    keyed.sort((a, b) => {
      if (!a.c || !b.c) return a.c ? -1 : b.c ? 1 : a.z.zoneId.localeCompare(b.z.zoneId);
      const rowA = Math.round(a.c[1] / ROW);
      const rowB = Math.round(b.c[1] / ROW);
      if (rowA !== rowB) return rowB - rowA;
      if (a.c[0] !== b.c[0]) return a.c[0] - b.c[0];
      return a.z.zoneId.localeCompare(b.z.zoneId);
    });
    keyed.forEach(({ z }, i) => out.set(zoneKey(z.parcelId, z.zoneId), i + 1));
  });
  return out;
}

/** The map label: zone number and the value of the active layer. */
export function zoneMapLabel(n: number | undefined, value: string): string {
  return n != null ? `${n} · ${value}` : value;
}

export interface ZoneRef {
  parcelId: string;
  zoneId: string;
}

type Listener = (sel: ZoneRef | null) => void;

function same(a: ZoneRef | null, b: ZoneRef | null): boolean {
  return a === b || (!!a && !!b && a.parcelId === b.parcelId && a.zoneId === b.zoneId);
}

/** The zone pointed at in the panel: a hover shows it, a click pins it until clicked again. */
function createZoneSelection() {
  let hovered: ZoneRef | null = null;
  let pinned: ZoneRef | null = null;
  const listeners = new Set<Listener>();
  const current = () => hovered ?? pinned;
  const emit = (before: ZoneRef | null) => {
    const now = current();
    if (!same(before, now)) listeners.forEach((l) => l(now));
  };
  return {
    get: current,
    hover(ref: ZoneRef | null) {
      const before = current();
      hovered = ref;
      emit(before);
    },
    pin(ref: ZoneRef | null) {
      const before = current();
      pinned = ref && same(ref, pinned) ? null : ref;
      hovered = null;
      emit(before);
    },
    subscribe(listener: Listener): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export const zoneSelection = createZoneSelection();

export type ZoneEmphasis = 'selected' | 'dimmed' | 'normal';

/** How the map paints a zone while another (or this one) is pointed at. */
export function zoneEmphasis(sel: ZoneRef | null, parcelId: string, zoneId: string): ZoneEmphasis {
  if (!sel || sel.parcelId !== parcelId) return 'normal';
  return sel.zoneId === zoneId ? 'selected' : 'dimmed';
}

export interface EmphasisStyle {
  fillAlpha: number;
  outlineWhite: boolean;
  outlineAlpha: number;
  labelAlpha: number;
  bold: boolean;
}

/** Paint of a zone: the pointed one stands out (opaque, white edge, bold label), its siblings fade. */
export function emphasisStyle(emphasis: ZoneEmphasis, baseAlpha: number): EmphasisStyle {
  if (emphasis === 'selected') return { fillAlpha: 0.75, outlineWhite: true, outlineAlpha: 1, labelAlpha: 1, bold: true };
  if (emphasis === 'dimmed') return { fillAlpha: baseAlpha * 0.35, outlineWhite: false, outlineAlpha: 0.4, labelAlpha: 0.45, bold: false };
  return { fillAlpha: baseAlpha, outlineWhite: false, outlineAlpha: 1, labelAlpha: 1, bold: false };
}
