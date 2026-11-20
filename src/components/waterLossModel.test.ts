import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { POLL_MAX_MS, POLL_MS, band, createWaterLossPoller, isSettled, reasonKey } from './waterLossModel';
import type { PollSnapshot } from './waterLossModel';
import type { WaterLossResponse } from '../types/waterLoss';

describe('band', () => {
  it('number', () => expect(band(3)).toEqual({ p50: 3, p10: null, p90: null }));
  it('object', () => expect(band({ p10: 1, p50: 2, p90: 3 })).toEqual({ p50: 2, p10: 1, p90: 3 }));
  it('null', () => expect(band(null)).toBeNull());
});
describe('isSettled', () => {
  it('done/failed/unavailable settle; queued/running do not', () => {
    for (const s of ['done', 'failed', 'unavailable'] as const) expect(isSettled(s)).toBe(true);
    for (const s of ['queued', 'running'] as const) expect(isSettled(s)).toBe(false);
  });
});
describe('reasonKey', () => {
  it('known', () => expect(reasonKey('not_sown')).toBe('waterLoss.reason.not_sown'));
  it('unknown -> other', () => expect(reasonKey('weird_x')).toBe('waterLoss.reason.other'));
});
describe('constants', () => {
  it('values', () => { expect(POLL_MS).toBe(5000); expect(POLL_MAX_MS).toBe(240000); });
});

const resp = (state: WaterLossResponse['state']) => ({ state, unavailable: [], result: null, season: null }) as unknown as WaterLossResponse;

describe('poller', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('polls with retry=false until done, then stops', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(resp('queued')).mockResolvedValueOnce(resp('running')).mockResolvedValue(resp('done'));
    const snaps: PollSnapshot[] = [];
    createWaterLossPoller({ fetch, onUpdate: (s) => snaps.push(s) }).start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(POLL_MS);
    await vi.advanceTimersByTimeAsync(POLL_MS);
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls.every((c) => c[0] === false)).toBe(true);
    expect(snaps[snaps.length - 1]?.phase).toBe('settled');
    await vi.advanceTimersByTimeAsync(POLL_MS * 5);
    expect(fetch).toHaveBeenCalledTimes(3);
  });
  it('a null response (404/network) is an error and does not keep polling', async () => {
    const fetch = vi.fn().mockResolvedValue(null);
    const snaps: PollSnapshot[] = [];
    createWaterLossPoller({ fetch, onUpdate: (s) => snaps.push(s) }).start();
    await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(snaps[snaps.length - 1]?.phase).toBe('error');
  });
  it('a throwing fetch is an error too', async () => {
    const fetch = vi.fn().mockRejectedValue(new Error('x'));
    const snaps: PollSnapshot[] = [];
    createWaterLossPoller({ fetch, onUpdate: (s) => snaps.push(s) }).start();
    await vi.advanceTimersByTimeAsync(POLL_MS * 2);
    expect(snaps[snaps.length - 1]?.phase).toBe('error');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('stops at the cap with the timeout phase', async () => {
    const fetch = vi.fn().mockResolvedValue(resp('running'));
    const snaps: PollSnapshot[] = [];
    createWaterLossPoller({ fetch, onUpdate: (s) => snaps.push(s) }).start();
    await vi.advanceTimersByTimeAsync(POLL_MAX_MS + POLL_MS);
    expect(snaps[snaps.length - 1]?.phase).toBe('timeout');
    const calls = fetch.mock.calls.length;
    await vi.advanceTimersByTimeAsync(POLL_MS * 5);
    expect(fetch).toHaveBeenCalledTimes(calls);
  });
  it('start(true) sends retry=true once, then polls with false', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(resp('queued')).mockResolvedValue(resp('done'));
    createWaterLossPoller({ fetch, onUpdate: () => {} }).start(true);
    await vi.advanceTimersByTimeAsync(POLL_MS);
    expect(fetch.mock.calls.map((c) => c[0])).toEqual([true, false]);
  });
  it('stop() clears the timer and ignores late responses', async () => {
    let resolve: (v: WaterLossResponse) => void = () => {};
    const fetch = vi.fn().mockImplementation(() => new Promise<WaterLossResponse>((r) => { resolve = r; }));
    const snaps: PollSnapshot[] = [];
    const p = createWaterLossPoller({ fetch, onUpdate: (s) => snaps.push(s) });
    p.start();
    p.stop();
    resolve(resp('running'));
    await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(snaps.map((s) => s.phase)).toEqual(['loading']);
  });
});
