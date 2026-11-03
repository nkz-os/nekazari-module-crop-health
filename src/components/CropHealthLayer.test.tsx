import { describe, expect, it, vi } from 'vitest';

vi.mock('@nekazari/sdk', () => ({ useViewer: () => ({ cesiumViewer: null }), useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock('@nekazari/viewer-kit', () => ({ DAY_MS: 86400000, latestAtOrBefore: () => null, snapToUtcDay: (d: number) => d }));

import { layerColor } from './CropHealthLayer';

const RED = '#dc2626';
const GREEN = '#16a34a';
const assessment = (fields: Record<string, unknown>) => ({ parcelId: 'p1', overallSeverity: 'LOW', ...fields }) as never;

describe('layerColor', () => {
  it('reads the composite index on its 0-100 scale', () => {
    expect(layerColor(assessment({ compositeStressIndex: 71.8 }), 'composite').fill).toBe(RED);
    expect(layerColor(assessment({ compositeStressIndex: 12 }), 'composite').fill).toBe(GREEN);
  });
  it('colours the cwsi mode from the resolved level, not from cwsiValue', () => {
    expect(layerColor(assessment({ waterStressLevel: 'high', cwsiValue: 0.1 }), 'cwsi').fill).toBe(RED);
    expect(layerColor(assessment({ waterStressLevel: 'none', cwsiValue: 0.9 }), 'cwsi').fill).toBe(GREEN);
  });
  it('paints grey for no_data, not_needed and a missing level', () => {
    for (const lv of ['no_data', 'not_needed', undefined]) {
      expect(layerColor(assessment({ waterStressLevel: lv, cwsiValue: 0.9 }), 'cwsi').fill).toBe('#9ca3af');
    }
  });
});
