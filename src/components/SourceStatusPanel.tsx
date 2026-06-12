import React, { useEffect, useState, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';

interface SensorInfo {
  metric: string;
  lastValue: number;
  lastTs: string;
  unit: string;
}

interface SourceBlock {
  status: string;
  freshness: string;
  lastDataAt: string | null;
  summary?: string;
  details?: Record<string, unknown>;
  sensors?: SensorInfo[];
  lastValue?: number;
  reason?: string;
  species?: string;
  eppoCode?: string;
  variety?: string;
  plantingDate?: string;
  harvestDate?: string | null;
  phenologyStage?: string;
  gddProgressPct?: number | null;
  source?: string;
  matchLevel?: string;
  alerts?: Array<{ type: string; name: string; conditions: string; confidence: string }>;
}

interface SourcesData {
  parcelId: string;
  checkedAt: string;
  sources: {
    soil: SourceBlock;
    iot: SourceBlock;
    weather: SourceBlock;
    satellite: { ndvi: SourceBlock; sar: SourceBlock };
    crop: SourceBlock;
    bioorchestrator: SourceBlock;
    risks: SourceBlock;
  };
}

interface SourceStatusPanelProps {
  parcelId: string;
  parcelName?: string;
}

const STATUS_DOT: Record<string, string> = {
  ok: '🟢',
  degraded: '🟡',
  unavailable: '🔴',
  error: '🔴',
  none: '⚪',
};

function StatusBadge({ status, label }: { status: string; label: string }) {
  const cls: Record<string, string> = {
    ok: 'bg-green-100 text-green-800 border border-green-200',
    degraded: 'bg-amber-100 text-amber-800 border border-amber-200',
    error: 'bg-red-100 text-red-800 border border-red-200',
    unavailable: 'bg-red-100 text-red-800 border border-red-200',
    none: 'bg-gray-100 text-gray-800 border border-gray-200',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium leading-4 ${cls[status] || cls.none}`}>
      {label}
    </span>
  );
}

function relativeTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'ahora';
    if (mins < 60) return `hace ${mins}min`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `hace ${hours}h`;
    return `hace ${Math.floor(hours / 24)}d`;
  } catch {
    return iso.slice(0, 10);
  }
}

const SourceStatusPanel: React.FC<SourceStatusPanelProps> = ({ parcelId, parcelName }) => {
  const { t } = useTranslation('crop-health');
  const [data, setData] = useState<SourcesData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true);
    try {
      const resp = await fetch(`/api/crop-health/sources?parcelId=${parcelId}`);
      if (resp.ok) {
        const json = await resp.json();
        setData(json);
        setError(null);
      } else {
        setError(`HTTP ${resp.status}`);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [parcelId]);

  useEffect(() => {
    setLoading(true);
    fetchData();
    const interval = setInterval(() => fetchData(), 60000);
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading) {
    return (
      <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3 animate-pulse space-y-2">
        {[1, 2, 3, 4, 5, 6].map(i => (
          <div key={i} className="h-4 bg-gray-200 rounded w-full" />
        ))}
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3 text-center">
        <p className="text-sm text-nkz-text-muted">{t('sources.error')}: {error}</p>
        <button
          className="text-xs text-nkz-accent-base underline mt-1 cursor-pointer bg-transparent border-none"
          onClick={() => { setLoading(true); fetchData(); }}
        >
          {t('sources.retry')}
        </button>
      </div>
    );
  }

  const src = data.sources;

  const countActive =
    (src.soil.status === 'ok' ? 1 : 0) +
    (src.iot.status === 'ok' ? 1 : 0) +
    (src.weather.status === 'ok' ? 1 : 0) +
    (src.satellite.ndvi.status === 'ok' ? 1 : 0) +
    (src.satellite.sar.status === 'ok' ? 1 : 0) +
    (src.crop.status === 'ok' ? 1 : 0) +
    (src.bioorchestrator.status === 'ok' ? 1 : 0);

  const countDegraded =
    (src.soil.freshness === 'stale' ? 1 : 0) +
    (src.iot.freshness === 'stale' ? 1 : 0) +
    (src.weather.freshness === 'stale' ? 1 : 0);

  const countDown =
    (src.soil.status === 'error' || (src.soil.status === 'unavailable' && src.soil.freshness === 'none') ? 1 : 0) +
    (src.iot.status === 'error' ? 1 : 0) +
    (src.satellite.sar.status === 'error' ? 1 : 0);

  return (
    <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3 shadow-sm">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-nkz-text-primary">
            {t('sources.title', { parcel: parcelName || parcelId })}
          </h3>
          <div className="flex flex-wrap gap-1 mt-1">
            <StatusBadge status="ok" label={`🟢 ${countActive} ${t('sources.activeCount')}`} />
            {countDegraded > 0 && <StatusBadge status="degraded" label={`🟡 ${countDegraded} ${t('sources.degradedCount')}`} />}
            {countDown > 0 && <StatusBadge status="error" label={`🔴 ${countDown} ${t('sources.downCount')}`} />}
          </div>
        </div>
        <button
          onClick={() => fetchData(true)}
          disabled={refreshing}
          className="text-lg text-nkz-accent-base hover:opacity-70 disabled:opacity-40 cursor-pointer bg-transparent border-none"
          title={t('sources.refresh')}
        >
          {refreshing ? '⏳' : '🔄'}
        </button>
      </div>

      {/* Source rows */}
      <div className="space-y-1.5 mt-2">
        <SourceRow icon="🌍" label={t('sources.soil.label')} status={src.soil.status}
          freshness={src.soil.freshness} lastDataAt={src.soil.lastDataAt}
          summary={src.soil.summary || t('sources.noData')} />
        <SourceRow icon="🌡️" label={t('sources.iot.label', { count: src.iot.sensors?.length || 0 })}
          status={src.iot.status} freshness={src.iot.freshness} lastDataAt={src.iot.lastDataAt}
          summary={src.iot.summary || t('sources.noData')} />
        <SourceRow icon="☁️" label={t('sources.weather.label')} status={src.weather.status}
          freshness={src.weather.freshness} lastDataAt={src.weather.lastDataAt}
          summary={src.weather.summary || t('sources.noData')} />
        <SourceRow icon="🛰️" label={t('sources.satellite.ndvi')} status={src.satellite.ndvi.status}
          freshness={src.satellite.ndvi.freshness} lastDataAt={src.satellite.ndvi.lastDataAt}
          summary={src.satellite.ndvi.lastValue != null ? `NDVI ${src.satellite.ndvi.lastValue.toFixed(2)}` : t('sources.noData')} />
        <SourceRow icon="📡" label={t('sources.satellite.sar')} status={src.satellite.sar.status}
          freshness={src.satellite.sar.freshness} lastDataAt={src.satellite.sar.lastDataAt}
          summary={src.satellite.sar.reason ? `— ${src.satellite.sar.reason}` : t('sources.noData')} />
        <SourceRow icon="🌾" label={t('sources.crop.label')} status={src.crop.status}
          freshness={src.crop.freshness} lastDataAt={src.crop.lastDataAt}
          summary={src.crop.species
            ? `${src.crop.species} · ${src.crop.variety || '?'}${src.crop.phenologyStage ? ` · ${src.crop.phenologyStage}` : ''}`
            : t('sources.crop.notSet')} />
        <SourceRow icon="📚" label={t('sources.bioorchestrator.label')} status={src.bioorchestrator.status}
          freshness={src.bioorchestrator.freshness} lastDataAt={src.bioorchestrator.lastDataAt}
          summary={src.bioorchestrator.summary || t('sources.noData')} />

        {src.risks.alerts && src.risks.alerts.length > 0 && (
          <div className="text-xs mt-2 pt-2 border-t border-nkz-border">
            <span className="text-nkz-text-muted">{t('sources.risks.label')}: </span>
            {src.risks.alerts.map((a, i) => (
              <span key={i} className="text-nkz-text-secondary">
                ⚠️ {a.name} ({a.conditions})
                {i < src.risks.alerts!.length - 1 ? ' · ' : ''}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

// ── SourceRow sub-component ──────────────────────────────────────────────

interface SourceRowProps {
  icon: string;
  label: string;
  status: string;
  freshness: string;
  lastDataAt: string | null;
  summary: string;
}

const SourceRow: React.FC<SourceRowProps> = ({ icon, label, status, lastDataAt, summary }) => (
  <div className="flex items-center gap-2 text-sm">
    <span className="w-5 text-center flex-shrink-0">{icon}</span>
    <span className="text-nkz-text-primary w-28 flex-shrink-0 truncate text-xs">{label}</span>
    <span className="flex-shrink-0 text-xs">{STATUS_DOT[status] || '❓'}</span>
    <span className="text-nkz-text-muted text-xs flex-shrink-0 w-16">{relativeTime(lastDataAt)}</span>
    <span className="text-nkz-text-secondary text-xs truncate">{summary}</span>
  </div>
);

export default SourceStatusPanel;
