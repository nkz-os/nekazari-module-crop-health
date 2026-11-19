import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const t = (k: string, o?: unknown) => (o && typeof o === 'object' ? `${k}:${JSON.stringify(o)}` : k);
vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t, i18n: { language: 'es' } }),
  useAuth: () => ({ user: { roles: mockRoles.current } }),
}));
const mockRoles = vi.hoisted(() => ({ current: ['Farmer'] as string[] }));
vi.mock('../api/cropHealthApi', () => ({ cropHealthFetch: vi.fn(), navigateTo: vi.fn() }));

import { MonitoringBannerView, NotMonitoredRow, SatelliteActivation, showSatelliteRow } from './SatelliteMonitoring';
import { canActivate } from '../hooks/useCanActivateMonitoring';

const cands = [
  { entity_id: 'urn:ngsi-ld:AgriParcel:p1', name: 'Acme North', species: 'Trigo', period: { start: '2026-03-01', end: null } },
  { entity_id: 'urn:ngsi-ld:AgriParcel:p2', name: 'Acme South', species: 'Cebada', period: { start: '2026-03-05', end: null } },
];
const view = (over: Record<string, unknown> = {}) => renderToStaticMarkup(
  <MonitoringBannerView t={t as never} lang="es" candidates={cands} partial={false} open={false} selected={new Set(cands.map(c => c.entity_id))}
    running={false} progress={{ done: 0, total: 0 }} summary={null} onOpen={() => {}} onCancel={() => {}} onToggle={() => {}}
    onConfirm={() => {}} {...over} />,
).replace(/&quot;/g, '"');

describe('MonitoringBannerView', () => {
  it('shows the count and the activate-all button', () => {
    const html = view();
    expect(html).toContain('monitoring.banner:{"n":2}');
    expect(html).toContain('monitoring.activateAll');
    expect(html).not.toContain('Acme North');
  });
  it('without candidates and without summary renders nothing', () => {
    expect(view({ candidates: [] })).toBe('');
  });
  it('the open list shows name, crop and date, all checked', () => {
    const html = view({ open: true });
    expect(html).toContain('Acme North');
    expect(html).toContain('Trigo');
    expect(html).toContain('monitoring.since');
    expect(html.match(/checked/g)?.length).toBeGreaterThanOrEqual(2);
    expect(html).toContain('monitoring.confirm:{"n":2}');
  });
  it('shows progress while running', () => {
    expect(view({ open: true, running: true, progress: { done: 1, total: 3 } })).toContain('monitoring.progress:{"done":1,"total":3}');
  });
  it('the summary lists activated and pending without calling the pending a failure', () => {
    const html = view({ candidates: [], summary: { ok: 2, pending: 1, forbidden: 0, error: 0 } });
    expect(html).toContain('monitoring.result.ok:{"n":2}');
    expect(html).toContain('monitoring.result.pending:{"n":1}');
    expect(html).not.toContain('monitoring.result.error');
  });
  it('adds the note when vegetation could not check every parcel', () => {
    expect(view({ partial: true })).toContain('monitoring.partial');
    expect(view({ partial: false })).not.toContain('monitoring.partial');
  });
});

describe('NotMonitoredRow', () => {
  const row = (over: Record<string, unknown> = {}) => renderToStaticMarkup(
    <NotMonitoredRow t={t as never} lang="es" canActivate periodStart="2026-03-01" outcome={null} busy={false} onActivate={() => {}} {...over} />,
  ).replace(/&quot;/g, '"');
  it('says there is no monitoring and offers the button', () => {
    const html = row();
    expect(html).toContain('monitoring.notMonitored');
    expect(html).toContain('monitoring.activate');
  });
  it('no button for a user who cannot activate', () => {
    const html = row({ canActivate: false });
    expect(html).toContain('monitoring.notMonitored');
    expect(html).not.toContain('<button');
  });
  it('explains each outcome in plain words and drops the button', () => {
    expect(row({ outcome: 'ok' })).toContain('monitoring.activated:{"date"');
    expect(row({ outcome: 'pending' })).toContain('monitoring.pending');
    expect(row({ outcome: 'forbidden' })).toContain('monitoring.forbidden');
    expect(row({ outcome: 'error' })).toContain('monitoring.failed');
    expect(row({ outcome: 'ok' })).not.toContain('<button');
  });
});

describe('canActivate', () => {
  it('matches the roles of the user, and shows when roles are unknown', () => {
    expect(canActivate(['Farmer'], ['Farmer', 'TenantAdmin'])).toBe(true);
    expect(canActivate(['Viewer'], ['Farmer', 'TenantAdmin'])).toBe(false);
    expect(canActivate([], ['Farmer'])).toBe(true);
    expect(canActivate(['Viewer'], [])).toBe(true);
  });
});


describe('SatelliteActivation (roles from the host)', () => {
  const html = (roles: string[], activationRoles: string[], outcome: string | null = null) => {
    mockRoles.current = roles;
    return renderToStaticMarkup(
      <SatelliteActivation parcelUrn="urn:ngsi-ld:AgriParcel:p1" periodStart={null} activationRoles={activationRoles}
        outcome={outcome as never} onOutcome={() => {}} onDone={() => {}} />);
  };
  it('known roles without permission: no button', () => {
    const out = html(['Viewer'], ['Farmer', 'TenantAdmin']);
    expect(out).toContain('monitoring.notMonitored');
    expect(out).not.toContain('<button');
  });
  it('a permitted role sees the button', () => {
    expect(html(['Farmer'], ['Farmer'])).toContain('<button');
  });
  it('unknown roles show the button (the 403 is explained later)', () => {
    expect(html([], ['Farmer'])).toContain('<button');
    expect(html(['Viewer'], [])).toContain('<button');
  });
  it('a lifted outcome is shown without a button', () => {
    const out = html(['Farmer'], ['Farmer'], 'pending');
    expect(out).toContain('monitoring.pending');
    expect(out).not.toContain('<button');
  });
});

describe('showSatelliteRow', () => {
  it('stays visible after the refetch drops not_monitored, while an outcome is held', () => {
    expect(showSatelliteRow('not_monitored', null)).toBe(true);
    expect(showSatelliteRow(undefined, 'ok')).toBe(true);
    expect(showSatelliteRow(undefined, null)).toBe(false);
  });
});
