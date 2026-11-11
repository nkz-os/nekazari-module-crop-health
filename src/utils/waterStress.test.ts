import { describe, expect, it } from 'vitest';
import { levelIntent, levelKey, levelSeverity, normalizeLevel, reservoirKey } from './waterStress';

describe('waterStress on a rainfed parcel', () => {
  it('names the level as how dry it is', () => {
    expect(levelKey('mild', 'rainfed')).toBe('waterStress.rainfed.mild');
    expect(levelKey('moderate', 'rainfed')).toBe('waterStress.rainfed.moderate');
    expect(levelKey('high', 'rainfed')).toBe('waterStress.rainfed.high');
    expect(levelKey('none', 'rainfed')).toBe('waterStress.level.none');
    expect(levelKey('not_needed', 'rainfed')).toBe('waterStress.level.not_needed');
    expect(levelKey('no_data', 'rainfed')).toBe('waterStress.level.no_data');
  });
  it('keeps the usual wording for an irrigated or unknown regime', () => {
    for (const regime of ['irrigated', null, undefined] as const) {
      expect(levelKey('high', regime)).toBe('waterStress.level.high');
      expect(levelIntent('high', regime, 'MEDIUM')).toBe('negative');
      expect(reservoirKey('high', regime)).toBe('soil.reservoir.high');
    }
  });
  it('is amber at most, red only when the severity was raised', () => {
    expect(levelIntent('mild', 'rainfed', 'MEDIUM')).toBe('warning');
    expect(levelIntent('moderate', 'rainfed', 'MEDIUM')).toBe('warning');
    expect(levelIntent('high', 'rainfed', 'MEDIUM')).toBe('warning');
    expect(levelIntent('high', 'rainfed', 'HIGH')).toBe('negative');
    expect(levelIntent('none', 'rainfed', 'LOW')).toBe('positive');
  });
  it('colours the map amber at most, red only when the severity was raised', () => {
    expect(levelSeverity('mild', 'rainfed', 'MEDIUM')).toBe('MEDIUM');
    expect(levelSeverity('moderate', 'rainfed', 'MEDIUM')).toBe('MEDIUM');
    expect(levelSeverity('high', 'rainfed', 'MEDIUM')).toBe('MEDIUM');
    expect(levelSeverity('high', 'rainfed', 'HIGH')).toBe('HIGH');
    expect(levelSeverity('none', 'rainfed', 'LOW')).toBe('LOW');
    expect(levelSeverity('no_data', 'rainfed', 'LOW')).toBeNull();
    for (const regime of ['irrigated', null, undefined] as const) {
      expect(levelSeverity('moderate', regime, 'MEDIUM')).toBe('HIGH');
      expect(levelSeverity('high', regime, 'MEDIUM')).toBe('CRITICAL');
    }
  });
  it('words the soil reserve without an irrigation instruction', () => {
    expect(reservoirKey('moderate', 'rainfed')).toBe('soil.reservoirRainfed.moderate');
    expect(reservoirKey('critical', 'rainfed')).toBe('soil.reservoirRainfed.critical');
  });
});

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
