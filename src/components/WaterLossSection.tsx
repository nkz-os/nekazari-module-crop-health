import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { MetricSection, ProgressBar } from './detail/MetricPrimitives';
import { getWaterLoss } from '../api/cropHealthApi';
import { band, createWaterLossPoller, reasonKey } from './waterLossModel';
import type { PollSnapshot } from './waterLossModel';
import type { WaterLossResult } from '../types/waterLoss';

const BTN = 'text-xs text-nkz-accent-base underline bg-transparent border-none cursor-pointer';
const NOTE = 'text-xs text-nkz-text-muted';

interface ViewProps {
  snap: PollSnapshot;
  onRetry: () => void;
  onRecheck: () => void;
}

export function WaterLossView({ snap, onRetry, onRecheck }: ViewProps) {
  const { t, i18n } = useTranslation('crop-health');
  const lang = i18n?.language || 'es';
  const num = (v: number) => new Intl.NumberFormat(lang, { maximumFractionDigits: 0 }).format(v);
  const date = (iso?: string | null) => (iso ? new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(iso)) : '');

  const header = (
    <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
      {t('waterLoss.title')}
    </span>
  );
  const wrap = (body: React.ReactNode) => <MetricSection>{header}{body}</MetricSection>;
  const data = snap.data;

  if (snap.phase === 'loading' || (snap.phase === 'polling')) {
    return wrap(<p className={NOTE}>{t('waterLoss.computing')}</p>);
  }
  const busy = data?.state === 'unavailable' && data.unavailable?.[0]?.reason === 'busy';
  if (snap.phase === 'timeout' || busy) {
    return wrap(
      <p className={NOTE}>{busy ? t(reasonKey('busy')) : t('waterLoss.stillComputing')} · <button type="button" className={BTN} onClick={onRecheck}>{t('waterLoss.checkAgain')}</button></p>,
    );
  }
  if (snap.phase === 'error' || data?.state === 'failed') {
    return wrap(
      <p className={NOTE}>{t('waterLoss.failed')} · <button type="button" className={BTN} onClick={onRetry}>{t('waterLoss.retry')}</button></p>,
    );
  }
  if (!data || data.state === 'unavailable' || !data.result) {
    const reason = data?.unavailable?.[0]?.reason ?? 'other';
    return wrap(<p className={NOTE}>{t(reasonKey(reason))}</p>);
  }

  const result: WaterLossResult = data.result;
  const season = data.season;
  const inSeason = season?.status === 'in_season';
  const range = (b: { p10: number | null; p90: number | null }) =>
    b.p10 != null && b.p90 != null ? ` ${t('waterLoss.range', { low: num(b.p10), high: num(b.p90) })}` : '';
  const total = band(result.total.water_gap_band ?? result.total.water_gap_pct);

  return wrap(
    <div className="space-y-2">
      <p className={NOTE}>{t('waterLoss.modelEstimate')}</p>
      {season && (
        <p className="text-xs text-nkz-text-primary">
          {inSeason
            ? t('waterLoss.cycle.in_season', { asOf: date(season.as_of) })
            : season.harvest_recorded
              ? t('waterLoss.cycle.complete', { harvest: date(season.harvest_recorded) })
              : t('waterLoss.cycle.completeNoHarvest')}
        </p>
      )}
      {total && (
        <p className="text-sm text-nkz-text-primary">
          {t('waterLoss.totalGap')}: <strong className="font-mono">{num(total.p50)}%</strong>{range(total)}
        </p>
      )}
      <div className="space-y-2">
        {result.stages.map((st) => {
          const gain = band(st.gain_pct_of_potential);
          const dates = st.start && st.end ? t('waterLoss.dates', { start: date(st.start), end: date(st.end) })
            : st.start ? t('waterLoss.since', { start: date(st.start) }) : '';
          return (
            <div key={st.key} className="space-y-0.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-nkz-text-primary">{t(`waterLoss.stage.${st.key}`)}</span>
                <span className={NOTE}>{t(`waterLoss.state.${st.state}`)}</span>
              </div>
              {dates && <p className={NOTE}>{dates}</p>}
              {st.state === 'complete' && gain && (
                <div>
                  <ProgressBar value={Math.max(0, gain.p50)} intent="warning" />
                  {range(gain) && <p className={NOTE}>{t('waterLoss.rangeLabel')}{range(gain)}</p>}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <p className={NOTE}>{t('waterLoss.notes.notAdditive')}</p>
      {inSeason && <p className={NOTE}>{t('waterLoss.notes.changesUntilHarvest')}</p>}
      <p className={NOTE}>{t('waterLoss.notes.flowering')}</p>
      <p className={NOTE}>{t(`waterLoss.validation.${result.validation.status === 'validated_forecast_crop' ? 'validated_forecast_crop' : 'unvalidated'}`)}</p>
      {result.sources.length > 0 && (
        <details>
          <summary className={`${NOTE} cursor-pointer`}>{t('waterLoss.sourcesTitle')}</summary>
          <ul className="list-disc pl-5">
            {result.sources.map((s) => (
              <li key={s.short} className={NOTE}>{s.short}{s.detail ? ` — ${s.detail}` : ''}</li>
            ))}
          </ul>
        </details>
      )}
    </div>,
  );
}

export default function WaterLossSection({ parcelId }: { parcelId: string }) {
  const [snap, setSnap] = useState<PollSnapshot>({ phase: 'loading', data: null });
  const poller = useRef<ReturnType<typeof createWaterLossPoller> | null>(null);

  useEffect(() => {
    const p = createWaterLossPoller({ fetch: (retry) => getWaterLoss(parcelId, retry), onUpdate: setSnap });
    poller.current = p;
    p.start(false);
    return () => { p.stop(); poller.current = null; };
  }, [parcelId]);

  return (
    <WaterLossView
      snap={snap}
      onRetry={() => poller.current?.start(true)}
      onRecheck={() => poller.current?.start(false)}
    />
  );
}
