import { describe, expect, it } from 'vitest';
import { newClientId, parseBbch, todayIso, validateObserved } from './phenologyBbch';

describe('phenologyBbch', () => {
  it('parses 1-2 digit codes only', () => {
    expect(parseBbch('0')).toBe(0);
    expect(parseBbch(' 31 ')).toBe(31);
    for (const bad of ['', '100', '-1', '3.5', 'ab', '1e1']) expect(parseBbch(bad)).toBeNull();
  });
  it('validates code and date, not in the future', () => {
    expect(validateObserved('31', '2027-03-02', '2027-03-02')).toBeNull();
    expect(validateObserved('', '2027-03-02', '2027-03-02')).toBe('code');
    expect(validateObserved('31', '', '2027-03-02')).toBe('date');
    expect(validateObserved('31', '2027-03-03', '2027-03-02')).toBe('future');
  });
  it('formats today in local time', () => {
    expect(todayIso(new Date(2027, 2, 2, 23, 59))).toBe('2027-03-02');
  });
  it('generates UUID v4', () => {
    const a = newClientId();
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(newClientId()).not.toBe(a);
  });
});
