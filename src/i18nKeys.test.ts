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

describe('zone strings', () => {
  for (const [lang, res] of Object.entries(resources)) {
    it(`${lang} has the zone selection hint`, () => {
      expect(typeof (res as any)['crop-health'].zones.selectHint).toBe('string');
    });
  }
});

describe('worklist and fleet parity', () => {
  const en = (resources.en as any)['crop-health'];
  for (const [lang, res] of Object.entries(resources)) {
    it(`${lang} has the worklist and fleet keys of en`, () => {
      const ns = (res as any)['crop-health'];
      expect(keys(ns.worklist).sort()).toEqual(keys(en.worklist).sort());
      expect(keys(ns.fleet).sort()).toEqual(['jobsToday', 'noData', 'surprises']);
      expect(keys(en.worklist).length).toBe(20);
    });
  }
});

describe('detail strings parity', () => {
  const en = (resources.en as any)['crop-health'];
  for (const [lang, res] of Object.entries(resources)) {
    it(`${lang} has the noCrop and tabs keys of en`, () => {
      const ns = (res as any)['crop-health'];
      expect(keys(ns.noCrop).sort()).toEqual(keys(en.noCrop).sort());
      expect(keys(ns.tabs).sort()).toEqual(['plant', 'risks', 'water']);
      expect(typeof ns.sources.generic).toBe('string');
      expect(typeof ns.sources.toggle).toBe('string');
      expect(typeof ns.yieldForecast.none).toBe('string');
    });
  }
});

describe('zone panel strings', () => {
  for (const [lang, res] of Object.entries(resources)) {
    it(`${lang} has the differing-zones keys`, () => {
      const z = (res as any)['crop-health'].zones;
      for (const k of ['showOnMap', 'rest', 'noDifference', 'parcelValue']) expect(typeof z[k]).toBe('string');
      expect(z.rest).toContain('{{list}}');
      expect(z.noDifference).toContain('{{count}}');
      expect(z.parcelValue).toContain('{{value}}');
    });
  }
});
