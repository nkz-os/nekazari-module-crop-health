import { describe, expect, it } from 'vitest';
import { levelIntent, levelKey, normalizeLevel } from './waterStress';

describe('waterStress mapping', () => {
  it('maps each level to one intent', () => {
    expect(levelIntent('none')).toBe('positive');
    expect(levelIntent('mild')).toBe('warning');
    expect(levelIntent('moderate')).toBe('warning');
    expect(levelIntent('high')).toBe('negative');
    expect(levelIntent('no_data')).toBe('neutral');
    expect(levelIntent('not_needed')).toBe('neutral');
  });
  it('maps each level to its i18n key', () => {
    expect(levelKey('mild')).toBe('waterStress.level.mild');
    expect(levelKey('not_needed')).toBe('waterStress.level.not_needed');
  });
  it('treats a missing or unknown level as no_data, never none', () => {
    for (const v of [undefined, null, '', 'bogus']) {
      expect(normalizeLevel(v)).toBe('no_data');
      expect(levelKey(v)).toBe('waterStress.level.no_data');
      expect(levelIntent(v)).toBe('neutral');
    }
  });
});
