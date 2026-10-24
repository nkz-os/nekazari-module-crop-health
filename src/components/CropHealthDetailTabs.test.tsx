import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

import CropHealthDetailTabs from './CropHealthDetailTabs';

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
});
