import { describe, expect, it, vi } from 'vitest';
vi.mock('@nekazari/sdk', () => ({ i18n: null }));
import { resources } from './i18n';

const keys = (o: any, p = ''): string[] => Object.entries(o).flatMap(([k, v]) =>
  v && typeof v === 'object' ? keys(v, `${p}${k}.`) : [`${p}${k}`]);

describe('i18n parity', () => {
  const en = (resources.en as any)['crop-health'];
  for (const [lang, res] of Object.entries(resources)) {
    const ns = (res as any)['crop-health'];
    it(`${lang} has the yieldForecast keys of en`, () => {
      expect(keys(ns.yieldForecast).sort()).toEqual(keys(en.yieldForecast).sort());
      expect(typeof ns.contextPanel.yieldGapInstantNote).toBe('string');
      expect(ns.detail?.baselineYield).toBeUndefined();
      expect(ns.detail?.predictedYield).toBeUndefined();
    });
  }
});
