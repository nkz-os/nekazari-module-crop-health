import type { WaterLossBand, WaterLossResponse } from '../types/waterLoss';

export const POLL_MS = 5000;
export const POLL_MAX_MS = 240000;

const KNOWN_REASONS = new Set([
  'not_sown', 'no_committed_crop', 'unsupported_crop', 'unknown_crop', 'irrigated_regime', 'no_regime',
  'no_sowing_date', 'sowing_in_future', 'season_too_old', 'season_ended', 'no_finished_season',
  'season_not_finished', 'busy', 'calendar_failed', 'engine_error', 'request_failed',
]);

export function band(v: number | WaterLossBand | null | undefined): { p50: number; p10: number | null; p90: number | null } | null {
  if (v == null) return null;
  if (typeof v === 'number') return { p50: v, p10: null, p90: null };
  return { p50: v.p50, p10: v.p10, p90: v.p90 };
}

export function isSettled(state: WaterLossResponse['state']): boolean {
  return state === 'done' || state === 'failed' || state === 'unavailable';
}

export function reasonKey(reason: string): string {
  return KNOWN_REASONS.has(reason) ? `waterLoss.reason.${reason}` : 'waterLoss.reason.other';
}

export type PollPhase = 'loading' | 'polling' | 'settled' | 'error' | 'timeout';
export interface PollSnapshot { phase: PollPhase; data: WaterLossResponse | null }

interface PollerDeps {
  fetch: (retry: boolean) => Promise<WaterLossResponse | null>;
  onUpdate: (snap: PollSnapshot) => void;
}

/** Polls until the job settles, the cap is hit or stop() is called. Only start(true) sends retry=true. */
export function createWaterLossPoller({ fetch, onUpdate }: PollerDeps) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let generation = 0;
  let last: WaterLossResponse | null = null;

  const clear = () => { if (timer) { clearTimeout(timer); timer = null; } };

  async function step(gen: number, startedAt: number, retry: boolean) {
    let data: WaterLossResponse | null = null;
    try { data = await fetch(retry); } catch { data = null; }
    if (gen !== generation) return;
    if (!data) { onUpdate({ phase: 'error', data: last }); return; }
    last = data;
    if (isSettled(data.state)) { onUpdate({ phase: 'settled', data }); return; }
    if (Date.now() - startedAt >= POLL_MAX_MS) { onUpdate({ phase: 'timeout', data }); return; }
    onUpdate({ phase: 'polling', data });
    timer = setTimeout(() => { void step(gen, startedAt, false); }, POLL_MS);
  }

  return {
    start(retry = false) {
      clear();
      generation += 1;
      onUpdate({ phase: 'loading', data: null });
      void step(generation, Date.now(), retry);
    },
    stop() { clear(); generation += 1; },
  };
}
