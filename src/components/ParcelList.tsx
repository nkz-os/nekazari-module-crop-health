import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { SeverityBadge } from './shared/SeverityBadge';

interface ParcelSummary {
  parcelId: string;
  parcelName?: string;
  cropName?: string;
  phenologyStage?: string;
  areaHa?: number;
  overallSeverity?: string;
  cwsiValue?: number;
  vigorIndex?: number;
  assessedAt?: string;
  hasData: boolean;
}

interface ParcelListProps {
  onSelectParcel: (parcelId: string) => void;
  selectedParcelId: string | null;
}

function relativeTime(iso: string | undefined): string {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'ahora';
  if (mins < 60) return `hace ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `hace ${hours}h`;
  return `hace ${Math.floor(hours / 24)}d`;
}

const ParcelList: React.FC<ParcelListProps> = ({ onSelectParcel, selectedParcelId }) => {
  const { t } = useTranslation('crop-health');
  const [parcels, setParcels] = useState<ParcelSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    const fetchParcels = async () => {
      try {
        const resp = await fetch('/api/crop-health/parcels');
        if (resp.ok) {
          const data = await resp.json();
          setParcels(data.parcels || []);
        } else {
          setError(`HTTP ${resp.status}`);
        }
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    fetchParcels();
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
      <div className="space-y-2 p-2">
        {[1, 2, 3, 4, 5].map(i => (
          <div key={i} className="animate-pulse h-14 bg-nkz-border rounded" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 text-center">
        <p className="text-nkz-text-muted text-sm">{t('error')}: {error}</p>
        <button
          className="text-nkz-accent-base text-xs mt-1 underline"
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
        <input
          type="text"
          placeholder={t('parcelList.search')}
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="w-full px-2 py-1.5 text-sm border border-nkz-border rounded bg-nkz-surface text-nkz-text-primary placeholder:text-nkz-text-muted focus:outline-none focus:border-nkz-accent-base"
        />
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 && (
          <p className="text-nkz-text-muted text-sm text-center p-4">{t('parcelList.noParcels')}</p>
        )}
        {filtered.map(p => (
          <button
            key={p.parcelId}
            onClick={() => onSelectParcel(p.parcelId)}
            className={`w-full text-left p-2 border-b border-nkz-border transition-colors hover:bg-nkz-surface-raised ${
              selectedParcelId === p.parcelId ? 'bg-nkz-accent-soft border-l-2 border-l-nkz-accent-base' : ''
            }`}
          >
            <div className="flex items-center gap-2">
              <SeverityBadge severity={p.overallSeverity || 'LOW'} dotOnly={p.hasData} />
              {!p.hasData && (
                <span className="w-2 h-2 rounded-full bg-gray-300 flex-shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-nkz-text-primary text-sm font-medium truncate">
                  {p.parcelName || p.parcelId}
                </p>
                <div className="flex items-center gap-2 text-xs text-nkz-text-muted">
                  {p.cropName && <span>{p.cropName}</span>}
                  {p.phenologyStage && <span>· {p.phenologyStage}</span>}
                  {p.areaHa != null && <span>· {p.areaHa.toFixed(1)} ha</span>}
                </div>
              </div>
              <div className="text-right flex-shrink-0">
                {p.hasData ? (
                  <>
                    {p.cwsiValue != null && (
                      <span
                        className="text-xs font-mono"
                        style={{ color: p.cwsiValue > 0.6 ? '#dc2626' : p.cwsiValue > 0.3 ? '#d97706' : '#16a34a' }}
                      >
                        CWSI {p.cwsiValue.toFixed(2)}
                      </span>
                    )}
                    <p className="text-nkz-text-muted text-xs">{relativeTime(p.assessedAt)}</p>
                  </>
                ) : (
                  <span className="text-nkz-text-muted text-xs">{t('parcelList.noData')}</span>
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
