import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { useCanActivateMonitoring } from '../hooks/useCanActivateMonitoring';
import { Button, Checkbox, ProgressBar } from '@nekazari/ui-kit';
import {
  activateMany,
  activateParcel,
  fetchCandidates,
  summaryParts,
  type ActivationOutcome,
  type ActivationSummary,
  type MonitoringCandidate,
} from '../services/vegetationMonitoring';

type TFn = (key: string, opts?: Record<string, unknown>) => string;

const localDate = (iso: string | null | undefined, lang: string): string =>
  iso ? new Date(iso).toLocaleDateString(lang) : '';

// ── Panel row: «no satellite monitoring» + Activate ─────────────────────────

interface NotMonitoredRowProps {
  t: TFn;
  lang: string;
  canActivate: boolean;
  periodStart: string | null;
  outcome: ActivationOutcome | null;
  busy: boolean;
  onActivate: () => void;
}

export const NotMonitoredRow: React.FC<NotMonitoredRowProps> = ({ t, lang, canActivate, periodStart, outcome, busy, onActivate }) => {
  const message = (() => {
    switch (outcome) {
      case 'ok':
        return periodStart
          ? t('monitoring.activated', { date: localDate(periodStart, lang) })
          : t('monitoring.activatedNoDate');
      case 'pending': return t('monitoring.pending');
      case 'forbidden': return t('monitoring.forbidden');
      case 'error': return t('monitoring.failed');
      default: return null;
    }
  })();
  return (
    <div className="flex items-center gap-2 text-xs pl-7">
      <span className="text-nkz-text-secondary">{message ?? t('monitoring.notMonitored')}</span>
      {outcome === null && canActivate && (
        <Button variant="secondary" size="sm" loading={busy} disabled={busy} onClick={onActivate}>
          {busy ? t('monitoring.activating') : t('monitoring.activate')}
        </Button>
      )}
    </div>
  );
};

/** The row stays while the panel holds an outcome, even after the refetch no longer says not_monitored. */
export const showSatelliteRow = (reason: string | undefined, outcome: ActivationOutcome | null): boolean =>
  reason === 'not_monitored' || outcome !== null;

/** The outcome lives in the panel (controlled), so a refetch cannot drop the message. */
export const SatelliteActivation: React.FC<{
  parcelUrn: string;
  periodStart: string | null;
  activationRoles: string[];
  outcome: ActivationOutcome | null;
  onOutcome: (outcome: ActivationOutcome) => void;
  onDone?: () => void;
}> = ({ parcelUrn, periodStart, activationRoles, outcome, onOutcome, onDone }) => {
  const { t, i18n } = useTranslation('crop-health');
  const allowed = useCanActivateMonitoring(activationRoles);
  const [busy, setBusy] = useState(false);
  const run = useCallback(async () => {
    setBusy(true);
    const result = await activateParcel(parcelUrn);
    setBusy(false);
    onOutcome(result);
    if (result === 'ok') onDone?.();
  }, [parcelUrn, onOutcome, onDone]);
  return (
    <NotMonitoredRow
      t={t as TFn}
      lang={i18n?.language || 'es'}
      canActivate={allowed}
      periodStart={periodStart}
      outcome={outcome}
      busy={busy}
      onActivate={run}
    />
  );
};

// ── Block above the parcel list ────────────────────────────────────────────

interface BannerViewProps {
  t: TFn;
  lang: string;
  candidates: MonitoringCandidate[];
  partial: boolean;
  open: boolean;
  selected: Set<string>;
  running: boolean;
  progress: { done: number; total: number };
  summary: ActivationSummary | null;
  onOpen: () => void;
  onCancel: () => void;
  onToggle: (entityId: string, checked: boolean) => void;
  onConfirm: () => void;
}

export const MonitoringBannerView: React.FC<BannerViewProps> = ({
  t, lang, candidates, partial, open, selected, running, progress, summary, onOpen, onCancel, onToggle, onConfirm,
}) => {
  if (candidates.length === 0 && !summary) return null;
  return (
    <div className="m-2 p-2.5 rounded-lg border border-nkz-border bg-nkz-surface-raised space-y-2">
      {candidates.length > 0 && (
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-nkz-text-primary">🛰️ {t('monitoring.banner', { n: candidates.length })}</p>
          {!open && !running && (
            <Button variant="secondary" size="sm" onClick={onOpen}>{t('monitoring.activateAll')}</Button>
          )}
        </div>
      )}
      {open && candidates.length > 0 && (
        <div className="space-y-1.5">
          {candidates.map((c) => (
            <Checkbox
              key={c.entity_id}
              id={`monitor-${c.entity_id}`}
              checked={selected.has(c.entity_id)}
              disabled={running}
              onChange={(checked) => onToggle(c.entity_id, checked)}
              label={[
                c.name || c.entity_id,
                c.species,
                c.period?.start ? t('monitoring.since', { date: localDate(c.period.start, lang) }) : null,
              ].filter(Boolean).join(' · ')}
            />
          ))}
          {running ? (
            <div className="space-y-1">
              <p className="text-xs text-nkz-text-muted">{t('monitoring.progress', { done: progress.done, total: progress.total })}</p>
              <ProgressBar value={progress.total ? Math.round((progress.done / progress.total) * 100) : 0} size="sm" />
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Button size="sm" disabled={selected.size === 0} onClick={onConfirm}>
                {t('monitoring.confirm', { n: selected.size })}
              </Button>
              <Button variant="ghost" size="sm" onClick={onCancel}>{t('monitoring.cancel')}</Button>
            </div>
          )}
        </div>
      )}
      {summary && <p className="text-xs text-nkz-text-secondary">{summaryParts(summary, t).join(', ')}</p>}
      {partial && <p className="text-xs text-nkz-text-muted">{t('monitoring.partial')}</p>}
    </div>
  );
};

export const MonitoringBanner: React.FC = () => {
  const { t, i18n } = useTranslation('crop-health');
  const [candidates, setCandidates] = useState<MonitoringCandidate[]>([]);
  const [partial, setPartial] = useState(false);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [summary, setSummary] = useState<ActivationSummary | null>(null);
  // The candidates route carries no roles: every user sees the block and a 403 is explained in the summary.

  const load = useCallback(async () => {
    const out = await fetchCandidates();
    setCandidates(out?.candidates ?? []);
    setPartial(out?.partial ?? false);
    return out?.candidates ?? [];
  }, []);

  useEffect(() => { void load(); }, [load]);

  const onOpen = () => {
    setSelected(new Set(candidates.map((c) => c.entity_id)));
    setSummary(null);
    setOpen(true);
  };

  const onToggle = (id: string, checked: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id); else next.delete(id);
      return next;
    });

  const onConfirm = async () => {
    const urns = candidates.map((c) => c.entity_id).filter((id) => selected.has(id));
    setRunning(true);
    const result = await activateMany(urns, (done, total) => setProgress({ done, total }));
    setRunning(false);
    setOpen(false);
    setSummary(result);
    await load();
  };

  return (
    <MonitoringBannerView
      t={t as TFn}
      lang={i18n?.language || 'es'}
      candidates={candidates}
      partial={partial}
      open={open}
      selected={selected}
      running={running}
      progress={progress}
      summary={summary}
      onOpen={onOpen}
      onCancel={() => setOpen(false)}
      onToggle={onToggle}
      onConfirm={onConfirm}
    />
  );
};
