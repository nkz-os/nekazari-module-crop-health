import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { MetricSection, Badge } from './detail/MetricPrimitives';
import { getYieldForecast, navigateTo, refreshYieldForecast, saveParcelRegime } from '../api/cropHealthApi';
import { detailLink, refreshSettled, rowsFor, toParcelUrn } from './yieldForecastModel';
import type { YieldForecastRecord } from '../types/yieldForecast';

const BTN = 'text-xs text-nkz-accent-base underline bg-transparent border-none cursor-pointer';
const POLL_MS = 5000;
const POLL_MAX_MS = 240000;

interface ViewProps {
  parcelId: string;
  record: YieldForecastRecord | null;
  loading: boolean;
  onRefresh: () => void;
  onRegime: (regime: 'rainfed' | 'irrigated') => void;
}

export function YieldForecastView({ parcelId, record, loading, onRefresh, onRegime }: ViewProps) {
  const { t, i18n } = useTranslation('crop-health');
  const lang = i18n?.language || 'es';
  const num = (v: number) => new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(v);
  const date = (iso?: string | null) => (iso ? new Intl.DateTimeFormat(lang, { dateStyle: 'medium' }).format(new Date(iso)) : '');
  const label = (group: string, key: string, vars: Record<string, string>) =>
    t(`yieldForecast.${group}.${key}`, { defaultValue: t(`yieldForecast.${group}.generic`, vars), ...vars });

  const header = (
    <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
      {t('yieldForecast.title')}
    </span>
  );
  if (loading || !record) {
    return <MetricSection>{header}<p className="text-xs text-nkz-text-muted">{t('yieldForecast.loading')}</p></MetricSection>;
  }
  const refresh = <button type="button" className={BTN} onClick={onRefresh}>{t('yieldForecast.refresh')}</button>;
  const rows = rowsFor(record);
  const season = record.season;
  const body = (() => {
    switch (record.status) {
      case 'not_computed':
        return <p className="text-xs text-nkz-text-muted">{t('yieldForecast.notComputed')} · {refresh}</p>;
      case 'failed':
        return <p className="text-xs text-nkz-text-muted">{t('yieldForecast.failed', { code: record.code ?? '' })} · {refresh}</p>;
      case 'unavailable':
        return (
          <div className="space-y-1">
            <p className="text-xs text-nkz-text-muted">{label('reason', record.reason ?? 'generic', { reason: record.reason ?? '', code: record.code ?? '' })}</p>
            {record.reason === 'no_regime' && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-nkz-text-primary">{t('yieldForecast.askRegime')}</span>
                <button type="button" className={BTN} onClick={() => onRegime('rainfed')}>{t('yieldForecast.rainfed')}</button>
                <button type="button" className={BTN} onClick={() => onRegime('irrigated')}>{t('yieldForecast.irrigated')}</button>
              </div>
            )}
          </div>
        );
      default:
        return (
          <div className="space-y-1">
            {record.status === 'season_ended' && <Badge intent="info">{t('yieldForecast.seasonEnded')}</Badge>}
            {rows.map((row) => (
              <div key={`${row.providerId}-${row.basis}`} className="flex items-center justify-between gap-2">
                <span className="text-xs text-nkz-text-primary">
                  {label('provider', row.providerId, { id: row.providerId })} · {label('basis', row.basis, { basis: row.basis })}
                </span>
                <span className="text-sm font-mono text-nkz-text-primary">
                  {t('yieldForecast.range', { low: num(row.low), high: num(row.high) })}
                  {row.median != null && ` · ${t('yieldForecast.median', { value: num(row.median) })}`}
                </span>
                <Badge intent={row.validation === 'validated' ? 'positive' : row.validation === 'experimental' ? 'warning' : 'default'}>
                  {t(`yieldForecast.validation.${row.validation}`)}
                </Badge>
              </div>
            ))}
            {season && (
              <p className="text-xs text-nkz-text-muted">
                {t('yieldForecast.season', { crop: season.crop, date: date(season.sowing.date),
                  regime: t(`yieldForecast.regime.${season.regime}`), asOf: date(season.as_of) })}
              </p>
            )}
            {record.computed_at && <p className="text-xs text-nkz-text-muted">{t('yieldForecast.computedAt', { date: date(record.computed_at) })}</p>}
            {record.last_error && <p className="text-xs text-nkz-text-muted">{t('yieldForecast.lastError', { reason: record.last_error.reason })}</p>}
            <div className="flex gap-3">
              {refresh}
              <button type="button" className={BTN} onClick={() => navigateTo(detailLink(parcelId, season))}>{t('yieldForecast.detail')}</button>
            </div>
          </div>
        );
    }
  })();
  return (
    <MetricSection>
      {header}
      {record.refreshing && <p className="text-xs text-nkz-text-muted">{t('yieldForecast.refreshing')}</p>}
      {body}
    </MetricSection>
  );
}

export default function YieldForecastSection({ parcelId }: { parcelId: string }) {
  const [record, setRecord] = useState<YieldForecastRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    const rec = await getYieldForecast(parcelId);
    setRecord(rec ?? { status: 'unavailable', reason: 'request_failed', refreshing: false });
    setLoading(false);
    return rec;
  }, [parcelId]);

  useEffect(() => { setLoading(true); void load(); return () => { if (timer.current) clearInterval(timer.current); }; }, [load]);

  const startRefresh = useCallback(async () => {
    const before = record ?? { status: 'not_computed', refreshing: false } as YieldForecastRecord;
    if (!(await refreshYieldForecast(parcelId))) return;
    setRecord({ ...before, refreshing: true });
    const started = Date.now();
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(async () => {
      const now = await getYieldForecast(parcelId);
      if ((now && refreshSettled(before, now)) || Date.now() - started > POLL_MAX_MS) {
        if (timer.current) clearInterval(timer.current);
        if (now) setRecord(now);
      }
    }, POLL_MS);
  }, [parcelId, record]);

  const onRegime = useCallback(async (regime: 'rainfed' | 'irrigated') => {
    if (await saveParcelRegime(toParcelUrn(parcelId), regime)) void startRefresh();
  }, [parcelId, startRefresh]);

  return <YieldForecastView parcelId={parcelId} record={record} loading={loading} onRefresh={() => void startRefresh()} onRegime={onRegime} />;
}
