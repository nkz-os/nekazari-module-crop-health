import { describe, expect, it, vi } from 'vitest';
import { activateMany, activateParcel, fetchCandidates, summaryParts } from './vegetationMonitoring';

const res = (status: number, body: unknown = {}) => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;
const URN = 'urn:ngsi-ld:AgriParcel:p1';

describe('activateParcel', () => {
  it('posts to the core with the session and maps the status', async () => {
    const f = vi.fn(async () => res(201));
    expect(await activateParcel(URN, f as never)).toBe('ok');
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/api/entities/parcels/urn%3Angsi-ld%3AAgriParcel%3Ap1/modules/vegetation-prime/activate');
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('include');
  });
  it.each([[200, 'ok'], [201, 'ok'], [502, 'pending'], [403, 'forbidden'], [404, 'error'], [500, 'error']])(
    'status %i is %s', async (status, outcome) => {
      expect(await activateParcel(URN, (async () => res(status)) as never)).toBe(outcome);
    });
  it('a network failure is an error, never a throw', async () => {
    expect(await activateParcel(URN, (async () => { throw new Error('down'); }) as never)).toBe('error');
  });
});

describe('activateMany', () => {
  it('goes one by one, reports progress and counts 201, 502 and 403', async () => {
    const statuses = [201, 502, 403];
    let inFlight = 0; let maxInFlight = 0;
    const f = vi.fn(async () => {
      inFlight++; maxInFlight = Math.max(maxInFlight, inFlight);
      await Promise.resolve();
      inFlight--;
      return res(statuses.shift() as number);
    });
    const progress: number[] = [];
    const out = await activateMany(['a', 'b', 'c'], (done) => progress.push(done), f as never);
    expect(out).toEqual({ ok: 1, pending: 1, forbidden: 1, error: 0 });
    expect(progress).toEqual([0, 1, 2, 3]);
    expect(maxInFlight).toBe(1);
  });
});

describe('summaryParts', () => {
  it('names only the non-zero outcomes', () => {
    const t = (k: string, o?: { n?: number }) => `${k}:${o?.n}`;
    expect(summaryParts({ ok: 2, pending: 1, forbidden: 0, error: 0 }, t as never))
      .toEqual(['monitoring.result.ok:2', 'monitoring.result.pending:1']);
  });
});

describe('fetchCandidates', () => {
  it('reads the user route with the session', async () => {
    const f = vi.fn(async () => res(200, { candidates: [{ entity_id: URN, name: 'Acme North' }], partial: true, failed: ['x'] }));
    const out = await fetchCandidates(f as never);
    expect(out).toEqual({ candidates: [{ entity_id: URN, name: 'Acme North' }], partial: true });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/api/vegetation/monitoring/candidates');
    expect(init.credentials).toBe('include');
  });
  it('is null when vegetation fails or the body is odd', async () => {
    expect(await fetchCandidates((async () => res(502)) as never)).toBeNull();
    expect(await fetchCandidates((async () => { throw new Error('x'); }) as never)).toBeNull();
    expect(await fetchCandidates((async () => res(200, { nope: 1 })) as never)).toBeNull();
  });
});
