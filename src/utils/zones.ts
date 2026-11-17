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
  differsFromParcel?: boolean;
  zoneRank?: number | null;
  zoneLevel?: string | null;
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

type Ring = number[][];

/** Polygon parts of a geometry, each as [outer ring, ...holes]. */
export function polygonParts(geometry: Geometry): Ring[][] {
  if (!geometry) return [];
  if (geometry.type === 'Polygon') return [geometry.coordinates as Ring[]];
  if (geometry.type === 'MultiPolygon') return geometry.coordinates as Ring[][];
  return [];
}

function ringArea(ring: Ring): number {
  let a = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) a += ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
  return a / 2;
}

function ringCentroid(ring: Ring): [number, number] | null {
  const a = ringArea(ring);
  if (Math.abs(a) < 1e-18) return null;
  let cx = 0;
  let cy = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const f = ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
    cx += (ring[j][0] + ring[i][0]) * f;
    cy += (ring[j][1] + ring[i][1]) * f;
  }
  return [cx / (6 * a), cy / (6 * a)];
}

function inRing(x: number, y: number, ring: Ring): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function inPart(x: number, y: number, part: Ring[]): boolean {
  return inRing(x, y, part[0]) && !part.slice(1).some((hole) => inRing(x, y, hole));
}

// Midpoint of the widest stretch of the part along the horizontal line y (even-odd over every ring).
function widestStretch(part: Ring[], y: number): [number, number] | null {
  const xs: number[] = [];
  for (const ring of part) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i];
      const [xj, yj] = ring[j];
      if (yi > y !== yj > y) xs.push(xi + ((y - yi) * (xj - xi)) / (yj - yi));
    }
  }
  xs.sort((a, b) => a - b);
  let best: [number, number] | null = null;
  let bestWidth = 0;
  for (let k = 0; k + 1 < xs.length; k += 2) {
    const w = xs[k + 1] - xs[k];
    if (w > bestWidth) {
      bestWidth = w;
      best = [(xs[k] + xs[k + 1]) / 2, y];
    }
  }
  return best;
}

/**
 * Where to put a zone's label: the centroid of its largest part (holes subtracted); if that falls
 * outside the part (a hole, or a concave shape) a point inside the part instead. Nested levels
 * (one level surrounding another) therefore never get their label in the neighbour's area.
 */
export function zoneLabelPoint(geometry: Geometry): [number, number] | null {
  const parts = polygonParts(geometry).filter((p) => p[0]?.length);
  if (parts.length === 0) return null;
  const area = (p: Ring[]) => Math.abs(ringArea(p[0])) - p.slice(1).reduce((sum, h) => sum + Math.abs(ringArea(h)), 0);
  const part = parts.reduce((best, p) => (area(p) > area(best) ? p : best));
  const c = ringCentroid(part[0]);
  if (c && inPart(c[0], c[1], part)) return c;
  const ys = part[0].map((pt) => pt[1]);
  const midY = (Math.min(...ys) + Math.max(...ys)) / 2;
  for (const y of [c?.[1], midY, midY + (Math.max(...ys) - Math.min(...ys)) / 4, midY - (Math.max(...ys) - Math.min(...ys)) / 4]) {
    if (y == null) continue;
    const pt = widestStretch(part, y);
    if (pt) return pt;
  }
  return part[0][0] as [number, number];
}

const LEVEL_CODES = ['high', 'medium', 'low', 'critical'];

/** Translated vigour name of a zone level ("Vigor alto"), or null when the zone has no known level. */
export function zoneLevelLabel(t: (key: string) => string, level: string | null | undefined): string | null {
  return level && LEVEL_CODES.includes(level) ? t(`zones.level.${level}`) : null;
}

export function zoneKey(parcelId: string | null | undefined, zoneId: string): string {
  return `${parcelId ?? ''}|${zoneId}`;
}

// Centroids closer than this (degrees, about 10 m) count as the same row, so the order reads
// west to east along it instead of jumping on rounding noise.
const ROW = 1e-4;

/**
 * Zone number per parcel, 1-based, read like a page: north to south, then west to east.
 * Zones without geometry come last, by id. If every zone of a parcel carries a `zoneRank`, that rank is used. Independent of the order the zones arrive in.
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
    // The backend's own order wins when it ranks every zone of the parcel.
    if (list.every((z) => typeof z.zoneRank === 'number')) {
      list.forEach((z) => out.set(zoneKey(z.parcelId, z.zoneId), z.zoneRank as number));
      return;
    }
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

/** Zones that differ from the parcel value, and the rest (same as the parcel). */
export function splitZones<T extends ZoneLike>(zones: T[]): { differing: T[]; rest: T[] } {
  const differing: T[] = [];
  const rest: T[] = [];
  for (const z of zones) (z.differsFromParcel ? differing : rest).push(z);
  return { differing, rest };
}

/** Zone numbers as a compact list: "1-2, 4-7" (runs of two or more become ranges). */
export function zoneNumberList(zones: ZoneLike[], numbers: Map<string, number>): string {
  const ns = zones
    .map((z) => numbers.get(zoneKey(z.parcelId, z.zoneId)))
    .filter((n): n is number => n != null)
    .sort((a, b) => a - b);
  const parts: string[] = [];
  for (let i = 0; i < ns.length; ) {
    let j = i;
    while (j + 1 < ns.length && ns[j + 1] === ns[j] + 1) j++;
    parts.push(j > i ? `${ns[i]}-${ns[j]}` : `${ns[i]}`);
    i = j + 1;
  }
  return parts.join(', ');
}

export const FIDELITY_KEYS = ['meteo', 'gdd', 'ndvi', 'sar', 'soil', 'twi', 'balance'] as const;

/** Which inputs of a zone are its own (zone-specific or sensor) and which are inherited from the parcel. */
export function fidelityLine(
  inputFidelity: Record<string, string> | undefined,
  t: (key: string) => string,
): { own: string[]; inherited: string[] } {
  const own: string[] = [];
  const inherited: string[] = [];
  if (!inputFidelity) return { own, inherited };
  for (const key of FIDELITY_KEYS) {
    const v = inputFidelity[key];
    const label = t(`zones.fidelity.${key}`);
    if (v === 'zone_specific' || v === 'iot_sensor') own.push(label);
    else if (v === 'parcel_inherited') inherited.push(label);
  }
  return { own, inherited };
}

/** The map description: the vigour level (or the zone number) and the value of the active layer. */
export function zoneMapLabel(n: number | undefined, value: string, levelLabel?: string | null): string {
  if (levelLabel) return `${levelLabel} · ${value}`;
  return n != null ? `${n} · ${value}` : value;
}

export interface ZoneRef {
  parcelId: string;
  zoneId: string;
}

/** The host's viewer route with the zone to light up (`/viewer` is redirected and drops the query). */
export function zoneViewerPath(ref: ZoneRef): string {
  return `/entities?parcel=${encodeURIComponent(ref.parcelId)}&zone=${encodeURIComponent(ref.zoneId)}`;
}

/** Whether a pinned zone (e.g. from a stale deep link) is among the loaded zones. */
export function pinnedZoneExists(
  pinned: ZoneRef | null,
  zones: { parcelId?: string; zoneId: string }[],
): boolean {
  if (!pinned) return true;
  return zones.some((z) => z.parcelId === pinned.parcelId && z.zoneId === pinned.zoneId);
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
    getPinned: () => pinned,
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

/** Severity colours of the map layer, shared with the legend so both always agree. */
export const SEVERITY_COLORS: Record<string, { fill: string; alpha: number }> = {
  LOW: { fill: '#16a34a', alpha: 0.3 },
  MEDIUM: { fill: '#d97706', alpha: 0.4 },
  HIGH: { fill: '#ea580c', alpha: 0.5 },
  CRITICAL: { fill: '#dc2626', alpha: 0.55 },
};

/** Fill opacity of a zone: only zones that differ from the parcel get the full colour. */
export function zoneFillAlpha(zone: { differsFromParcel?: boolean }, base: number): number {
  return zone.differsFromParcel ? base : 0.1;
}

/** The map label of a zone: "Vigor alto · Sano" when it has a level, else just its number (the value goes to the infobox). */
export function zoneLabelText(n: number | undefined, levelLabel?: string | null, healthLabel?: string | null): string {
  if (levelLabel) return healthLabel ? `${levelLabel} · ${healthLabel}` : levelLabel;
  return String(n ?? '');
}

/** Big, bold numbers that shrink with distance so they never pile up when zoomed out. */
export function zoneLabelStyle(emphasis: ZoneEmphasis): { font: string; scaleByDistance: [number, number, number, number] } {
  return {
    font: emphasis === 'selected' ? 'bold 24px sans-serif' : 'bold 20px sans-serif',
    scaleByDistance: [500, 1.0, 5000, 0.5],
  };
}

/** True when no zone differs from the parcel: the map then shows one value for the whole parcel. */
export function parcelOnlyLabel(zones: Array<{ differsFromParcel?: boolean }>): boolean {
  return !zones.some((z) => z.differsFromParcel);
}

/** The zone a deep link points at (`?parcel=<id>&zone=<id>`), if both are present. */
export function readZoneFromLocation(search: string): ZoneRef | null {
  const params = new URLSearchParams(search);
  const parcelId = params.get('parcel');
  const zoneId = params.get('zone');
  return parcelId && zoneId ? { parcelId, zoneId } : null;
}

/** Ground outline of a zone (a clamped polyline: Cesium draws no outline on terrain-clamped polygons). */
export function zoneOutlineStyle(emphasis: ZoneEmphasis, colorHex: string): { colorHex: string; alpha: number; width: number } {
  if (emphasis === 'selected') return { colorHex: '#ffffff', alpha: 1, width: 4 };
  if (emphasis === 'dimmed') return { colorHex, alpha: 0.4, width: 2 };
  return { colorHex, alpha: 1, width: 2 };
}
