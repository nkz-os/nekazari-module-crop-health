import { isoToUtcMs, utcMsToIso } from '@nekazari/viewer-kit';
import { cropHealthFetch } from '../api/cropHealthApi';
import type { HistoryPoint } from '../types/assessment';

export const PARCEL_URN_PREFIX = 'urn:ngsi-ld:AgriParcel:';

/** Short parcel id (the one assessments are keyed by) from a viewer entity id. */
export function parcelIdFromEntityId(entityId: string): string {
  return entityId.replace(PARCEL_URN_PREFIX, '');
}

/** A history point placed on the shared timeline scale (UTC-midnight ms). */
export interface DailyPoint extends HistoryPoint {
  time: number;
}

/**
 * Assessment history of one parcel between two UTC-midnight instants, `to`
 * inclusive. Failures and empty ranges both come back as [] (the fetch helper
 * has already logged the cause).
 */
export async function fetchAssessmentHistory(
  parcelId: string,
  fromMs: number,
  toMs: number,
): Promise<HistoryPoint[]> {
  const from = utcMsToIso(fromMs);
  const to = utcMsToIso(toMs);
  if (!from || !to) return [];
  const res = await cropHealthFetch<{ points: HistoryPoint[] }>(
    `/assessments/history?parcelId=${encodeURIComponent(parcelId)}&from=${from}&to=${to}`,
  );
  return res?.points ?? [];
}

/**
 * One point per UTC day, oldest first. The endpoint returns timestamps, so a
 * day with several assessments would otherwise repeat on the axis; the last
 * assessment of the day wins. Points with an unparseable date are dropped.
 */
export function toDailyPoints(points: HistoryPoint[]): DailyPoint[] {
  const byDay = new Map<number, DailyPoint>();
  const ordered = [...points].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  for (const p of ordered) {
    const time = isoToUtcMs(p.date);
    if (Number.isNaN(time)) continue;
    byDay.set(time, { ...p, time });
  }
  return Array.from(byDay.values());
}
