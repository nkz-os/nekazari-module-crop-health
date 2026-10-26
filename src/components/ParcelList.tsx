import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { cropHealthFetch } from '../api/cropHealthApi';
import { formatRelativeTime } from '../utils/relativeTime';
import type { ParcelSummary } from '../types/assessment';

import { jobLabelKey, whenLabel, freshnessTone, semaphore } from '../utils/worklist';

type TFn = (key: string, opts?: Record<string, unknown>) => string;

const DOT_COLORS: Record<string, string> = {
  red: 'var(--nkz-color-danger)',
  amber: 'var(--nkz-color-warning)',
  green: 'var(--nkz-color-success)',
  grey: 'var(--nkz-color-text-muted)',
};

const TONE_CLASS: Record<string, string> = {
  muted: 'text-nkz-text-muted',
  warning: 'text-nkz-warning',
  danger: 'text-nkz-danger',
};

export interface WorklistSummary {
  surprises: number;
  jobsToday: number;
  noData: number;
}

function jobLine(p: ParcelSummary, t: TFn, lang: string): string {
  let job = p.nextJob;
  if (!job && p.cropStatus === 'active' && !p.hasData) {
    job = { kind: 'pending_assessment', when: null, detail: {} };
  }
  let text = t(jobLabelKey(job), (job?.detail ?? {}) as Record<string, unknown>);
  const w = job?.kind === 'sow' ? job.detail?.workability : undefined;
  if (w === 'optimal' || w === 'too_wet' || w === 'too_dry') {
    text += `: ${t(`worklist.workability.${w}`)}`;
  }
  const when = whenLabel(job, t as (k: string) => string, lang);
  return when ? `${text} · ${when}` : text;
}

interface ParcelRowsProps {
  rows: ParcelSummary[];
  selectedParcelId: string | null;
  onSelect: (parcelId: string, parcelName: string) => void;
  t: TFn;
  lang: string;
}

export const ParcelRows: React.FC<ParcelRowsProps> = ({ rows, selectedParcelId, onSelect, t, lang }) => (
  <>
    {rows.map(p => {
      const phase = p.phenologyStage ? t(`phenology.stage.${p.phenologyStage}`, { defaultValue: p.phenologyStage }) : '';
      const cropLine = p.cropStatus === 'none'
        ? t('worklist.noActiveCrop')
        : [p.cropName, phase].filter(Boolean).join(' · ');
      return (
        <button
          key={p.parcelId}
          onClick={() => onSelect(p.parcelId, p.parcelName || '')}
          className={`w-full text-left p-2.5 border-b border-nkz-border transition-colors cursor-pointer bg-transparent ${
            selectedParcelId === p.parcelId
              ? 'bg-nkz-accent-soft border-l-[3px] border-l-nkz-accent-base'
              : 'hover:bg-nkz-surface-raised border-l-[3px] border-l-transparent'
          }`}
        >
          <div className="flex items-start gap-2">
            <span
              className="inline-block flex-shrink-0 mt-1"
              style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: DOT_COLORS[semaphore(p)] }}
            />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-nkz-text-primary truncate">{p.parcelName || p.parcelId}</p>
              <p className="text-xs text-nkz-text-muted truncate">{cropLine}</p>
              <p className="text-xs text-nkz-text-primary mt-0.5">{jobLine(p, t, lang)}</p>
              {p.surprise && (
                <p className="text-xs text-nkz-warning mt-0.5">
                  {t(`worklist.surprise.${p.surprise.code}`, p.surprise.detail as Record<string, unknown>)}
                </p>
              )}
            </div>
            {p.hasData && p.assessedAt && (
              <span className={`text-xs flex-shrink-0 ${TONE_CLASS[freshnessTone(p.freshness)]}`}>
                {formatRelativeTime(p.assessedAt, t as never)}
              </span>
            )}
          </div>
        </button>
      );
    })}
  </>
);

interface ParcelListProps {
  onSelectParcel: (parcelId: string, parcelName: string) => void;
  selectedParcelId: string | null;
  onParcelsLoaded?: (parcels: ParcelSummary[]) => void;
  onSummary?: (s: WorklistSummary) => void;
}

const ParcelList: React.FC<ParcelListProps> = ({ onSelectParcel, selectedParcelId, onParcelsLoaded, onSummary }) => {
  const { t, i18n } = useTranslation('crop-health');
  const [parcels, setParcels] = useState<ParcelSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    const fetchData = async () => {
      try {
        const resp = await cropHealthFetch<{ parcels: ParcelSummary[]; summary?: WorklistSummary }>('/parcels');
        const rows = resp?.parcels ?? [];
        setParcels(rows);
        onParcelsLoaded?.(rows);
        onSummary?.(resp?.summary ?? { surprises: 0, jobsToday: 0, noData: 0 });
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const filtered = parcels.filter(p => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      (p.parcelName || p.parcelId).toLowerCase().includes(q) ||
      (p.cropName || '').toLowerCase().includes(q)
    );
  });

  if (loading) {
    return (
      <div className="p-2 space-y-2">
        <div className="animate-pulse mb-2">
          <div className="h-9 bg-nkz-border rounded" />
        </div>
        {[1, 2, 3, 4, 5].map(i => (
          <div key={i} className="animate-pulse h-14 bg-nkz-surface-sunken rounded" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 text-center">
        <p className="text-sm text-nkz-text-muted">{t('error')}: {error}</p>
        <button
          className="text-xs text-nkz-accent-base underline mt-1 cursor-pointer bg-transparent border-none"
          onClick={() => window.location.reload()}
        >
          {t('retry')}
        </button>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Search */}
      <div className="p-2">
        <div className="relative">
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-nkz-text-muted">🔍</span>
          <input
            type="text"
            placeholder={t('parcelList.search')}
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-7 pr-2.5 py-1.5 text-sm border border-nkz-border rounded-lg bg-nkz-surface text-nkz-text-primary placeholder:text-nkz-text-muted focus:outline-none focus:border-nkz-accent-base focus:ring-1 focus:ring-nkz-accent-base/20"
          />
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 && (
          <p className="text-sm text-nkz-text-muted text-center p-4">{t('parcelList.noParcels')}</p>
        )}
        <ParcelRows
          rows={filtered}
          selectedParcelId={selectedParcelId}
          onSelect={onSelectParcel}
          t={t as TFn}
          lang={i18n?.language || 'es'}
        />
      </div>
    </div>
  );
};

export default ParcelList;
