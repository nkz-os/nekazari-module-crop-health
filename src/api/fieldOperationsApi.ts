import { API_ORIGIN } from './apiOrigin';

const RECORD_URL = `${API_ORIGIN}/api/field-operations/operations/record`;

export interface ObservedStageInput {
  parcelId: string;
  /** BBCH code, 0-99. */
  code: number;
  /** YYYY-MM-DD */
  date: string;
  /** Free text; empty falls back to `BBCH <code>`. */
  note: string;
  /** UUID v4, generated once per form open so a retry is idempotent. */
  clientId: string;
}

export type RecordResult =
  | { ok: true; duplicate: boolean }
  | { ok: false; code: string };

export function buildObservedStageBody(input: ObservedStageInput) {
  const note = input.note.trim();
  return {
    operation_type: 'scouting' as const,
    parcel_id: input.parcelId,
    date: input.date,
    notes: note || `BBCH ${input.code}`,
    phenologicalStage: input.code,
    client_id: input.clientId,
  };
}

/** Records a `scouting` operation carrying the observed BBCH stage (field-operations). */
export async function recordObservedStage(input: ObservedStageInput): Promise<RecordResult> {
  let resp: Response;
  try {
    resp = await fetch(RECORD_URL, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildObservedStageBody(input)),
    });
  } catch (err) {
    console.warn('[crop-health] record observed stage network error', err);
    return { ok: false, code: 'network_error' };
  }
  let payload: any = null;
  try {
    payload = await resp.json();
  } catch {
    payload = null;
  }
  if (resp.ok) return { ok: true, duplicate: payload?.duplicate === true };
  const code = payload?.detail?.code ?? payload?.code;
  return { ok: false, code: typeof code === 'string' ? code : `http_${resp.status}` };
}
