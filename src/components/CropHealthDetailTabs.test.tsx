import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));
vi.mock('./YieldForecastSection', () => ({ default: () => null }));
vi.mock('./CropHealthRisksPanel', () => ({ default: () => <i>risks-panel</i> }));
vi.mock('./ZoneHealthPanel', () => ({ default: () => null }));

import CropHealthDetailTabs, { formatBaselineC, recommendationHints } from './CropHealthDetailTabs';

const render = (extra: Record<string, unknown>) =>
  renderToStaticMarkup(
    <CropHealthDetailTabs
      parcelId="p1"
      assessment={{ parcelId: 'p1', overallSeverity: 'LOW', ...extra } as never}
      phenology={null}
      trend={[]}
      correlation={[]}
      correlationStats={null}
    />,
  );

describe('CropHealthDetailTabs water stress lines', () => {
  it('shows the open-field index alone when there is no under-panel index', () => {
    const html = render({ waterStressIndex: 0.444, waterStressFidelity: 'iot_sensor' });
    expect(html).toContain('detail.waterStress 0.44 · detail.fidelity.iot_sensor');
    expect(html).not.toContain('detail.waterStressUnderPanel');
  });
  it('labels both indices when the parcel has an under-panel index', () => {
    const html = render({
      waterStressIndex: 0.444, waterStressFidelity: 'iot_sensor',
      underPanelWaterStressIndex: 0.556, underPanelWaterStressFidelity: 'iot_sensor',
    });
    expect(html).toContain('detail.waterStressOpenField 0.44');
    expect(html).toContain('detail.waterStressUnderPanel 0.56 · detail.fidelity.iot_sensor');
  });
  it('says unavailable for an unknown fidelity or a missing index', () => {
    const html = render({
      waterStressIndex: 0.4, waterStressFidelity: 'bogus',
      underPanelWaterStressIndex: null, underPanelWaterStressFidelity: 'iot_sensor',
    });
    expect(html).toContain('detail.waterStressOpenField detail.fidelity.unavailable');
    expect(html).toContain('detail.waterStressUnderPanel detail.fidelity.unavailable');
  });
  it.each(['parcel_weather', 'regional_proxy'])('labels a %s index as parcel', (fidelity) => {
    const html = render({ waterStressIndex: 0.3, waterStressFidelity: fidelity });
    expect(html).toContain('detail.waterStressParcel 0.30');
  });
  it('labels a model index as parcel even with an under-panel index', () => {
    const html = render({
      waterStressIndex: 0.3, waterStressFidelity: 'parcel_weather',
      underPanelWaterStressIndex: 0.5, underPanelWaterStressFidelity: 'iot_sensor',
    });
    expect(html).toContain('detail.waterStressParcel 0.30');
    expect(html).toContain('detail.waterStressUnderPanel 0.50');
  });
});

describe('CropHealthDetailTabs tabs', () => {
  it('has exactly water, plant and risks', () => {
    const html = render({});
    expect(html).toContain('tabs.water');
    expect(html).toContain('tabs.plant');
    expect(html).toContain('tabs.risks');
    expect(html).not.toContain('tabs.yield');
    expect(html).not.toContain('tabs.analytics');
  });
});

describe('CropHealthDetailTabs without an assessment', () => {
  const r = (diseases: unknown[]) => renderToStaticMarkup(
    <CropHealthDetailTabs parcelId="p1" assessment={null} phenology={null} trend={[]} correlation={[]}
      correlationStats={null} diseases={diseases as never} />,
  );
  it('still shows the disease risks when there are some', () => {
    expect(r([{ disease: 'downy_mildew' }])).toContain('risks-panel');
    expect(r([])).not.toContain('risks-panel');
  });
});

describe('formatBaselineC', () => {
  it('shows a dash, never a bare unit, when absent', () => {
    expect(formatBaselineC(undefined)).toBe('—');
    expect(formatBaselineC(null)).toBe('—');
    expect(formatBaselineC(Number.NaN)).toBe('—');
  });
  it('formats a baseline', () => {
    expect(formatBaselineC(2)).toBe('2.0°C');
    expect(formatBaselineC(7.04)).toBe('7.0°C');
  });
});

describe('CropHealthDetailTabs technician water stress block', () => {
  const phenology = {
    water_stress_reference: {
      baselines: [
        { id: 'b1', a0C: 1.5, a1CPerKpa: -2.1, upper: { form: 'fixed', valueC: 4.2 }, valid: {}, sourceId: 'src1', ref: 'r' },
        { id: 'b2', a0C: 7.7, a1CPerKpa: -3.3, upper: { form: 'fixed', valueC: 5.5 }, valid: {}, sourceId: 'src2', ref: 'r' },
      ],
      stages: {}, sourceIds: ['src1', 'src2'],
      citations: [
        { sourceId: 'src1', text: 'Author (2019)', url: 'https://doi.org/10.1000/x' },
        { sourceId: 'src2', text: 'Other (2020)' },
      ],
    },
  };
  const withBlock = (extra: Record<string, unknown>) =>
    renderToStaticMarkup(
      <CropHealthDetailTabs
        parcelId="p1"
        assessment={{ parcelId: 'p1', overallSeverity: 'LOW', ...extra } as never}
        phenology={phenology as never}
        trend={[]} correlation={[]} correlationStats={null}
      />,
    );
  it('shows level, method, value, baseline and the source link', () => {
    const h = withBlock({ waterStressLevel: 'mild', waterStressMethod: 'cwsi_sensor', cwsiValue: 0.234, vpdKpa: 1.8, waterStressReferenceSources: ['src1'], cwsiBaselineId: 'b1' });
    expect(h).toContain('waterStress.level.mild');
    expect(h).toContain('waterStress.method.cwsi_sensor');
    expect(h).toContain('0.23');
    expect(h).toContain('1.50');
    expect(h).toContain('href="https://doi.org/10.1000/x"');
    expect(h).toContain('Author (2019)');
    expect(h).not.toContain('>D1<');
  });
  it('lists only the citations of the sources the assessment used', () => {
    const h = withBlock({ waterStressLevel: 'mild', waterStressMethod: 'cwsi_sensor', waterStressReferenceSources: ['src1'] });
    expect(h).toContain('Author (2019)');
    expect(h).not.toContain('Other (2020)');
  });
  it('lists no sources when the assessment names none, never all of them', () => {
    for (const sources of [[], undefined, null]) {
      const h = withBlock({ waterStressLevel: 'mild', waterStressMethod: 'balance', waterStressReferenceSources: sources });
      expect(h).not.toContain('Author (2019)');
      expect(h).not.toContain('Other (2020)');
      expect(h).not.toContain('waterStress.technician.sources');
    }
  });
  it('shows the baseline whose id the assessment used, and none when it is unknown', () => {
    const used = withBlock({ waterStressLevel: 'mild', waterStressMethod: 'cwsi_sensor', cwsiBaselineId: 'b2' });
    expect(used).toContain('7.70');
    expect(used).not.toContain('1.50');
    for (const id of [undefined, null, 'nope']) {
      const h = withBlock({ waterStressLevel: 'mild', waterStressMethod: 'cwsi_sensor', cwsiBaselineId: id });
      expect(h).not.toContain('7.70');
      expect(h).not.toContain('1.50');
      expect(h).not.toContain('waterStress.technician.baseline');
    }
  });
  it('shows Ks for the balance method', () => {
    const h = withBlock({ waterStressLevel: 'moderate', waterStressMethod: 'balance', waterStressIndex: 0.3 });
    expect(h).toContain('waterStress.method.balance');
    expect(h).toContain('0.70');
  });
  it('reads a single source id compacted by Orion as a list', () => {
    const h = withBlock({ waterStressLevel: 'mild', waterStressMethod: 'cwsi_sensor', waterStressReferenceSources: 'src1' });
    expect(h).toContain('Author (2019)');
    expect(h).not.toContain('Other (2020)');
    // a compacted id is matched whole, never as a substring
    expect(withBlock({ waterStressLevel: 'mild', waterStressMethod: 'cwsi_sensor', waterStressReferenceSources: 'src12' })).not.toContain('Author (2019)');
  });
  it('cites FAO-56 for the balance method', () => {
    const ph = { water_stress_reference: { ...phenology.water_stress_reference, citations: [
      ...phenology.water_stress_reference.citations, { sourceId: 'fao56', text: 'Allen et al. (1998) FAO-56' },
    ] } };
    const r = (extra: Record<string, unknown>) => renderToStaticMarkup(
      <CropHealthDetailTabs parcelId="p1" assessment={{ parcelId: 'p1', overallSeverity: 'LOW', ...extra } as never}
        phenology={ph as never} trend={[]} correlation={[]} correlationStats={null} />,
    );
    expect(r({ waterStressLevel: 'mild', waterStressMethod: 'balance', waterStressReferenceSources: [] })).toContain('Allen et al. (1998) FAO-56');
    expect(r({ waterStressLevel: 'mild', waterStressMethod: 'cwsi_sensor', waterStressReferenceSources: ['src1'] })).not.toContain('FAO-56');
  });
  it('says a zone level comes from the parcel balance', () => {
    expect(withBlock({ zoneId: 'z1', waterStressLevel: 'mild', waterStressMethod: 'balance' })).toContain('waterStress.technician.parcelBalance');
    expect(withBlock({ waterStressLevel: 'mild', waterStressMethod: 'balance' })).not.toContain('waterStress.technician.parcelBalance');
    expect(withBlock({ zoneId: 'z1', waterStressLevel: 'mild', waterStressMethod: 'cwsi_sensor' })).not.toContain('waterStress.technician.parcelBalance');
  });
  it('gives the hint of the method behind a high level, and no deficit hint when water is not needed', () => {
    const hints = (extra: Record<string, unknown>) =>
      recommendationHints({ parcelId: 'p1', overallSeverity: 'LOW', ...extra } as never, ((k: string) => k) as never);
    expect(hints({ waterStressLevel: 'high', waterStressMethod: 'cwsi_sensor' })).toContain('detail.hints.cwsiHigh');
    const ks = hints({ waterStressLevel: 'high', waterStressMethod: 'balance' });
    expect(ks).toContain('detail.hints.ksHigh');
    expect(ks).not.toContain('detail.hints.cwsiHigh');
    expect(hints({ waterStressLevel: 'not_needed', waterStressMethod: 'balance', waterBalanceDeficit: -20 })).not.toContain('detail.hints.deficit');
    expect(hints({ waterStressLevel: 'mild', waterStressMethod: 'balance', waterBalanceDeficit: -20 })).toContain('detail.hints.deficit');
  });
  it('renders the phase basis only when present', () => {
    expect(withBlock({ waterStressLevel: 'mild', waterStressMethod: 'balance', waterStressPhaseBasis: 'gdd_ndvi' })).toContain('waterStress.phaseBasis.gdd_ndvi');
    expect(withBlock({ waterStressLevel: 'mild', waterStressMethod: 'balance' })).not.toContain('waterStress.phaseBasis');
  });
});
