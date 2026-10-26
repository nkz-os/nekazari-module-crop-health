import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock('@nekazari/viewer-kit', () => ({ SlotShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));

import CropHealthMapModeWidget from './CropHealthMapModeWidget';

describe('CropHealthMapModeWidget legend', () => {
  const html = renderToStaticMarkup(<CropHealthMapModeWidget />);
  it('explains the numbers and the outline', () => {
    expect(html).toContain('legend.numbers');
    expect(html).toContain('legend.outline');
  });
  it('shows the four severity colours with their labels', () => {
    for (const s of ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']) expect(html).toContain(`severity.${s}`);
    for (const c of ['#16a34a', '#d97706', '#ea580c', '#dc2626']) expect(html).toContain(c);
  });
});
