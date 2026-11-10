import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildObservedStageBody, recordObservedStage } from './fieldOperationsApi';

const input = { parcelId: 'urn:p1', code: 31, date: '2027-03-02', note: '', clientId: '0b6f0d3e-1111-4222-8333-444455556666' };
const respond = (status: number, body: unknown) =>
  vi.fn().mockResolvedValue({ ok: status < 400, status, json: async () => body });

afterEach(() => vi.unstubAllGlobals());

describe('buildObservedStageBody', () => {
  it('sends the scouting body of the contract, with a default note', () => {
    expect(buildObservedStageBody(input)).toEqual({
      operation_type: 'scouting', parcel_id: 'urn:p1', date: '2027-03-02',
      notes: 'BBCH 31', phenologicalStage: 31, client_id: input.clientId,
    });
  });
  it('keeps the typed note, trimmed', () => {
    expect(buildObservedStageBody({ ...input, note: '  tillers visible ' }).notes).toBe('tillers visible');
  });
});

describe('recordObservedStage', () => {
  it('POSTs with credentials to the runtime origin', async () => {
    const f = respond(201, { operation_id: 'x' });
    vi.stubGlobal('fetch', f);
    expect(await recordObservedStage(input)).toEqual({ ok: true, duplicate: false });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe('/api/field-operations/operations/record'); // API_ORIGIN is empty in tests
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('include');
    expect(JSON.parse(init.body).client_id).toBe(input.clientId);
  });
  it('treats a 200 duplicate as success', async () => {
    vi.stubGlobal('fetch', respond(200, { duplicate: true }));
    expect(await recordObservedStage(input)).toEqual({ ok: true, duplicate: true });
  });
  it('returns the error code of the response', async () => {
    vi.stubGlobal('fetch', respond(422, { detail: { code: 'invalid_phenological_stage' } }));
    expect(await recordObservedStage(input)).toEqual({ ok: false, code: 'invalid_phenological_stage' });
  });
  it('falls back to the HTTP status, and to network_error', async () => {
    vi.stubGlobal('fetch', respond(502, {}));
    expect(await recordObservedStage(input)).toEqual({ ok: false, code: 'http_502' });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('down')));
    expect(await recordObservedStage(input)).toEqual({ ok: false, code: 'network_error' });
  });
});
