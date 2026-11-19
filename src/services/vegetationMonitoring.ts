import { API_ORIGIN } from '../api/apiOrigin';

export const PARCEL_URN_PREFIX = 'urn:ngsi-ld:AgriParcel:';

export type ActivationOutcome = 'ok' | 'pending' | 'forbidden' | 'error';
export type ActivationSummary = Record<ActivationOutcome, number>;

export interface MonitoringCandidate {
  entity_id: string;
  name?: string;
  species?: string;
  lifecycle?: string;
  period?: { start: string | null; end: string | null };
}

type FetchFn = typeof fetch;
type TFn = (key: string, opts?: Record<string, unknown>) => string;

/** Parcels of the tenant with a crop and no satellite monitoring (vegetation, user route). Null when unknown. */
export async function fetchCandidates(
  fetchImpl: FetchFn = fetch,
): Promise<{ candidates: MonitoringCandidate[]; partial: boolean } | null> {
  try {
    const resp = await fetchImpl(`${API_ORIGIN}/api/vegetation/monitoring/candidates`, { credentials: 'include' });
    if (!resp.ok) return null;
    const body = await resp.json();
    if (!body || !Array.isArray(body.candidates)) return null;
    return { candidates: body.candidates as MonitoringCandidate[], partial: body.partial === true };
  } catch (err) {
    console.warn('[crop-health] monitoring candidates unavailable', err);
    return null;
  }
}

/**
 * Turns the satellite monitoring of a parcel on through the core's per-parcel gate.
 * 502 means the dispatch failed and the core's reconciler retries on its own.
 */
export async function activateParcel(parcelUrn: string, fetchImpl: FetchFn = fetch): Promise<ActivationOutcome> {
  const url = `${API_ORIGIN}/api/entities/parcels/${encodeURIComponent(parcelUrn)}/modules/vegetation-prime/activate`;
  let resp: Response;
  try {
    resp = await fetchImpl(url, { method: 'POST', credentials: 'include' });
  } catch (err) {
    console.warn('[crop-health] monitoring activation network error', err);
    return 'error';
  }
  if (resp.ok) return 'ok';
  if (resp.status === 502) return 'pending';
  if (resp.status === 403) return 'forbidden';
  return 'error';
}

/** Activates the parcels one at a time; `onProgress(done, total)` fires before each and after the last. */
export async function activateMany(
  parcelUrns: string[],
  onProgress?: (done: number, total: number) => void,
  fetchImpl: FetchFn = fetch,
): Promise<ActivationSummary> {
  const summary: ActivationSummary = { ok: 0, pending: 0, forbidden: 0, error: 0 };
  for (let i = 0; i < parcelUrns.length; i++) {
    onProgress?.(i, parcelUrns.length);
    summary[await activateParcel(parcelUrns[i], fetchImpl)] += 1;
  }
  onProgress?.(parcelUrns.length, parcelUrns.length);
  return summary;
}

/** One phrase per outcome that happened (a pending parcel is not a failure). */
export function summaryParts(summary: ActivationSummary, t: TFn): string[] {
  return (['ok', 'pending', 'forbidden', 'error'] as const)
    .filter((k) => summary[k] > 0)
    .map((k) => t(`monitoring.result.${k}`, { n: summary[k] }));
}
