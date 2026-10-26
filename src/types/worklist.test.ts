import { describe, it, expect } from 'vitest';
import { semaphore, freshnessTone, whenLabel, jobLabelKey } from '../utils/worklist';
import type { ParcelSummary, NextJob } from './assessment';

const base: ParcelSummary = {
  parcelId: 'urn:ngsi-ld:AgriParcel:p1',
  hasData: true,
  cropStatus: 'active',
  freshness: 'fresh',
  stale: false,
  nextJob: null,
  surprise: null,
  plannedCrop: null,
  lastAssessment: null,
};
const row = (o: Partial<ParcelSummary>): ParcelSummary => ({ ...base, ...o });
const job = (kind: NextJob['kind'], when: NextJob['when']): NextJob => ({ kind, when, detail: {} });

describe('semaphore', () => {
  it('grey when no crop', () => expect(semaphore(row({ cropStatus: 'none' }))).toBe('grey'));
  it('grey when no data', () => expect(semaphore(row({ hasData: false }))).toBe('grey'));
  it('red on surprise', () =>
    expect(semaphore(row({ surprise: { code: 'x', detail: {} } }))).toBe('red'));
  it('red on CRITICAL/HIGH', () => {
    expect(semaphore(row({ overallSeverity: 'CRITICAL' }))).toBe('red');
    expect(semaphore(row({ overallSeverity: 'HIGH' }))).toBe('red');
  });
  it('amber on job today', () =>
    expect(semaphore(row({ nextJob: job('irrigate', 'today') }))).toBe('amber'));
  it('amber on MEDIUM', () => expect(semaphore(row({ overallSeverity: 'MEDIUM' }))).toBe('amber'));
  it('green otherwise', () => {
    expect(semaphore(row({ overallSeverity: 'LOW' }))).toBe('green');
    expect(semaphore(row({ nextJob: job('harvest', '2027-01-01') }))).toBe('green');
  });
});

describe('freshnessTone', () => {
  it('maps', () => {
    expect(freshnessTone('fresh')).toBe('muted');
    expect(freshnessTone('none')).toBe('muted');
    expect(freshnessTone('aging')).toBe('warning');
    expect(freshnessTone('stale')).toBe('danger');
  });
});

describe('whenLabel', () => {
  const t = (k: string) => `T:${k}`;
  it('today', () => expect(whenLabel(job('sow', 'today'), t, 'en')).toBe('T:worklist.when.today'));
  it('date', () =>
    expect(whenLabel(job('harvest', '2027-03-05T12:00:00Z'), t, 'en')).toBe(
      new Date('2027-03-05T12:00:00Z').toLocaleDateString('en'),
    ));
  it('null when', () => expect(whenLabel(job('none_until', null), t, 'en')).toBe(''));
  it('null job', () => expect(whenLabel(null, t, 'en')).toBe(''));
});

describe('jobLabelKey', () => {
  it('kind', () => expect(jobLabelKey(job('treat', 'today'))).toBe('worklist.job.treat'));
  it('null', () => expect(jobLabelKey(null)).toBe('worklist.job.none'));
});
