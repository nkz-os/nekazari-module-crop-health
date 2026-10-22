import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { cropHealthFetch } from '../api/cropHealthApi';
import { formatRelativeTime } from '../utils/relativeTime';
import type { ParcelSummary } from '../types/assessment';

const INDICATOR_COLORS: Record<string, string> = {
  green: 'var(--nkz-color-success)',
  blue: 'var(--nkz-color-info)',
  yellow: 'var(--nkz-color-warning)',
  red: 'var(--nkz-color-danger)',
  grey: 'var(--nkz-color-text-muted)',
};

function relativeTime(iso: string | undefined, t: ReturnType<typeof useTranslation>['t']): string {
  return formatRelativeTime(iso, t);
}

interface ParcelListProps {
  onSelectParcel: (parcelId: string, parcelName: string) => void;
  selectedParcelId: string | null;
  onParcelsLoaded?: (parcels: ParcelSummary[]) => void;
}

const ParcelList: React.FC<ParcelListProps> = ({ onSelectParcel, selectedParcelId, onParcelsLoaded }) => {
  const { t } = useTranslation('crop-health');
  const [parcels, setParcels] = useState<ParcelSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [parcelsResp, sourcesResp] = await Promise.all([
          cropHealthFetch<{ parcels: ParcelSummary[] }>('/parcels'),
          cropHealthFetch<{ parcels: Array<{ parcelId: string; healthIndicator: string; sourcesActive: number; sourcesDegraded: number; sourcesDown: number }> }>('/sources'),
        ]);

        const parcelsData = parcelsResp ?? { parcels: [] };
        const sourcesData = sourcesResp ?? { parcels: [] };

        const sourceMap: Record<string, { healthIndicator: string; sourcesActive: number; sourcesDegraded: number; sourcesDown: number }> = {};
        for (const s of sourcesData.parcels || []) {
          sourceMap[s.parcelId] = s;
        }

        const merged = (parcelsData.parcels || []).map((p: ParcelSummary) => ({
          ...p,
          healthIndicator: sourceMap[p.parcelId]?.healthIndicator || 'grey',
          sourcesActive: sourceMap[p.parcelId]?.sourcesActive || 0,
          sourcesDegraded: sourceMap[p.parcelId]?.sourcesDegraded || 0,
          sourcesDown: sourceMap[p.parcelId]?.sourcesDown || 0,
        }));

        setParcels(merged);
        onParcelsLoaded?.(merged);
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
        {filtered.map(p => (
          <button
            key={p.parcelId}
            onClick={() => onSelectParcel(p.parcelId, p.parcelName || "")}
            className={`w-full text-left p-2.5 border-b border-nkz-border transition-colors cursor-pointer bg-transparent ${
              selectedParcelId === p.parcelId
                ? 'bg-nkz-accent-soft border-l-[3px] border-l-nkz-accent-base'
                : 'hover:bg-nkz-surface-raised border-l-[3px] border-l-transparent'
            }`}
          >
            <div className="flex items-start gap-2">
              <span
                title={p.healthIndicator || 'grey'}
                className="inline-block flex-shrink-0 mt-1"
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  backgroundColor: INDICATOR_COLORS[p.healthIndicator || 'grey'] || 'var(--nkz-color-text-muted)',
                }}
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-nkz-text-primary truncate">
                  {p.parcelName || p.parcelId}
                </p>
                <div className="flex items-center gap-2 text-xs text-nkz-text-muted mt-0.5">
                  {p.cropName && <span>🌾 {p.cropName}</span>}
                  {p.phenologyStage && <span>🌸 {p.phenologyStage}</span>}
                  {p.areaHa != null && <span>📐 {p.areaHa.toFixed(1)} ha</span>}
                </div>
              </div>
              <div className="text-right flex-shrink-0">
                {p.hasData ? (
                  <>
                    {p.cwsiValue != null && (
                      <span
                        className="text-xs font-mono"
                        style={{ color: p.cwsiValue > 0.6 ? 'var(--nkz-color-danger)' : p.cwsiValue > 0.3 ? 'var(--nkz-color-warning)' : 'var(--nkz-color-success)' }}
                      >
                        CWSI {p.cwsiValue.toFixed(2)}
                      </span>
                    )}
                    <p className="text-xs text-nkz-text-muted">{relativeTime(p.assessedAt, t)}</p>
                  </>
                ) : (
                  <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium leading-4 bg-nkz-surface-sunken text-nkz-text-secondary border border-nkz-border">
                    {t('parcelList.noData')}
                  </span>
                )}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
};

export default ParcelList;
