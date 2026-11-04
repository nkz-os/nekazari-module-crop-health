/**
 * The only mapping from the backend's water-stress level to a UI intent and an i18n key.
 * The level is resolved by the backend (one set of cuts); nothing here reads cwsiValue.
 * A missing or unknown level is `no_data`, never `none`.
 */
export type WaterStressLevel = 'none' | 'mild' | 'moderate' | 'high' | 'no_data' | 'not_needed';
export type LevelIntent = 'positive' | 'warning' | 'negative' | 'neutral';

const INTENT: Record<WaterStressLevel, LevelIntent> = {
  none: 'positive',
  mild: 'warning',
  moderate: 'warning',
  high: 'negative',
  no_data: 'neutral',
  not_needed: 'neutral',
};

export function normalizeLevel(level: string | null | undefined): WaterStressLevel {
  return level != null && Object.prototype.hasOwnProperty.call(INTENT, level) ? (level as WaterStressLevel) : 'no_data';
}

export function levelIntent(level: string | null | undefined): LevelIntent {
  return INTENT[normalizeLevel(level)];
}

export function levelKey(level: string | null | undefined): string {
  return `waterStress.level.${normalizeLevel(level)}`;
}

/** Map-layer fill per level: reuses the severity palette, grey is applied by the caller for neutral. */
export const LEVEL_SEVERITY: Record<WaterStressLevel, 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | null> = {
  none: 'LOW',
  mild: 'MEDIUM',
  moderate: 'HIGH',
  high: 'CRITICAL',
  no_data: null,
  not_needed: null,
};
