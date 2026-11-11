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

export type Regime = 'rainfed' | 'irrigated' | null | undefined;
const DRY_LEVELS: readonly WaterStressLevel[] = ['mild', 'moderate', 'high'];

/**
 * A rainfed parcel cannot be irrigated, so its stress is a state, not an alarm: amber at most,
 * red only when the backend raised the severity (a high level in a water-sensitive stage).
 */
export function levelIntent(
  level: string | null | undefined, regime?: Regime, severity?: string | null,
): LevelIntent {
  const lv = normalizeLevel(level);
  if (regime === 'rainfed' && lv === 'high') {
    return severity === 'HIGH' || severity === 'CRITICAL' ? 'negative' : 'warning';
  }
  return INTENT[lv];
}

/** On a rainfed parcel the level reads as how dry it is ("Dry"), not as a stress to act on. */
export function levelKey(level: string | null | undefined, regime?: Regime): string {
  const lv = normalizeLevel(level);
  return regime === 'rainfed' && DRY_LEVELS.includes(lv) ? `waterStress.rainfed.${lv}` : `waterStress.level.${lv}`;
}

/** The soil reserve sentence: without an irrigation instruction on a rainfed parcel. */
export function reservoirKey(stressLevel: string | null | undefined, regime?: Regime): string {
  return `soil.${regime === 'rainfed' ? 'reservoirRainfed' : 'reservoir'}.${stressLevel ?? 'none'}`;
}

/** Map-layer severity of a level: a rainfed parcel is amber at most, as in `levelIntent`. */
export function levelSeverity(
  level: string | null | undefined, regime?: Regime, severity?: string | null,
): 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | null {
  const lv = normalizeLevel(level);
  if (regime === 'rainfed' && (lv === 'moderate' || lv === 'high')) {
    return lv === 'high' && (severity === 'HIGH' || severity === 'CRITICAL') ? 'HIGH' : 'MEDIUM';
  }
  return LEVEL_SEVERITY[lv];
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
