import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';

interface DiseaseRisk {
    disease: string;
    crop: string;
    risk_level: string;
    conditions: string;
    confidence: string;
    lwd_method?: string;
    source_model?: string;
    recommended_action: string;
    parcelId?: string;
}

const DISEASE_LABELS: Record<string, string> = {
    downy_mildew: 'Mildiu',
    apple_scab: 'Sarna del manzano',
    alternaria: 'Alternaria',
    powdery_mildew: 'Oídio',
};

const DISEASE_EMOJIS: Record<string, string> = {
    downy_mildew: '🍇',
    apple_scab: '🍎',
    alternaria: '🍅',
    powdery_mildew: '🌿',
};

function RiskBadge({ level }: { level: string }) {
    const classes: Record<string, string> = {
        LOW: 'bg-green-100 text-green-800 border border-green-200',
        MEDIUM: 'bg-amber-100 text-amber-800 border border-amber-200',
        HIGH: 'bg-red-100 text-red-800 border border-red-200',
    };
    return (
        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium leading-4 ${classes[level] || classes.LOW}`}>
            {level}
        </span>
    );
}

interface Props {
    parcelId: string;
    parcelName?: string;
}

const DiseaseRiskContextPanel: React.FC<Props> = ({ parcelId, parcelName }) => {
    const { t } = useTranslation('crop-health');
    const [risks, setRisks] = useState<DiseaseRisk[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!parcelId) return;
        setLoading(true);
        fetch(`/api/crop-health/diseases/active?parcelId=${encodeURIComponent(parcelId)}`)
            .then(r => r.ok ? r.json() : null)
            .then(data => setRisks(data?.risks || []))
            .catch(() => {})
            .finally(() => setLoading(false));
    }, [parcelId]);

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                <span className="text-base">🦠</span>
                <span className="text-sm font-semibold text-nkz-text-primary">
                    {t('diseaseRisk')}{parcelName ? ` — ${parcelName}` : ''}
                </span>
            </div>

            {loading ? (
                <div className="space-y-2">
                    <div className="animate-pulse h-14 bg-nkz-surface-raised rounded-lg" />
                    <div className="animate-pulse h-14 bg-nkz-surface-raised rounded-lg" />
                </div>
            ) : !risks.length ? (
                <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-4 text-center">
                    <span className="text-xl">🛡️</span>
                    <p className="text-sm text-nkz-text-muted mt-1">{t('diseaseRiskNone')}</p>
                </div>
            ) : (
                risks.map((r, i) => {
                    const color = r.risk_level === 'HIGH' ? '#dc2626' : r.risk_level === 'MEDIUM' ? '#d97706' : '#16a34a';
                    return (
                        <div key={i} className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 border-l-[3px]" style={{ borderLeftColor: color }}>
                            <div className="flex items-center justify-between">
                                <span className="text-sm font-semibold text-nkz-text-primary">
                                    {(DISEASE_EMOJIS[r.disease] || '🦠')} {DISEASE_LABELS[r.disease] || r.disease}
                                </span>
                                <RiskBadge level={r.risk_level} />
                            </div>
                            {r.crop && <p className="text-xs text-nkz-text-muted mt-1">🌾 {r.crop}</p>}
                            <p className="text-xs text-nkz-text-secondary mt-1">{r.conditions}</p>
                            <p className="text-xs font-semibold mt-1.5" style={{ color }}>{r.recommended_action}</p>
                            <div className="text-xs text-nkz-text-muted mt-1">
                                {r.confidence && `${r.confidence} confidence`}
                                {r.lwd_method && ` · LWD: ${r.lwd_method}`}
                                {r.source_model && ` · ${r.source_model}`}
                            </div>
                        </div>
                    );
                })
            )}
        </div>
    );
};

export default DiseaseRiskContextPanel;
