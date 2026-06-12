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

const DiseaseRiskWidget: React.FC = () => {
    const { t } = useTranslation('crop-health');
    const [risks, setRisks] = useState<DiseaseRisk[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchRisks = async () => {
            try {
                const resp = await fetch('/api/crop-health/diseases/active');
                if (resp.ok) {
                    const data = await resp.json();
                    setRisks(data.risks || []);
                }
            } catch {} finally { setLoading(false); }
        };
        fetchRisks();
        const interval = setInterval(fetchRisks, 30 * 60 * 1000);
        return () => clearInterval(interval);
    }, []);

    if (loading) {
        return (
            <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-4">
                <div className="space-y-2">
                    <div className="animate-pulse h-12 bg-gray-100 rounded-lg" />
                    <div className="animate-pulse h-12 bg-gray-100 rounded-lg" />
                </div>
            </div>
        );
    }

    if (!risks.length) return null;

    return (
        <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-3 space-y-2">
            <div className="flex items-center gap-2 mb-1">
                <span className="text-base">🦠</span>
                <span className="text-sm font-semibold text-nkz-text-primary">{t('diseaseRisk')}</span>
            </div>
            {risks.map((r, i) => {
                const color = r.risk_level === 'HIGH' ? '#dc2626' : r.risk_level === 'MEDIUM' ? '#d97706' : '#16a34a';
                return (
                    <div key={i} className="bg-nkz-surface border border-nkz-border rounded-lg p-2.5 border-l-[3px]" style={{ borderLeftColor: color }}>
                        <div className="flex items-center justify-between">
                            <span className="text-sm font-semibold text-nkz-text-primary">
                                {(DISEASE_EMOJIS[r.disease] || '🦠')} {DISEASE_LABELS[r.disease] || r.disease}
                            </span>
                            <RiskBadge level={r.risk_level} />
                        </div>
                        {(r.crop || r.parcelId) && (
                            <div className="text-xs text-nkz-text-muted mt-1">
                                {r.crop && <span>🌾 {r.crop}</span>}
                                {r.parcelId && <span className="ml-2">📋 {r.parcelId}</span>}
                            </div>
                        )}
                        <p className="text-xs text-nkz-text-secondary mt-1">{r.conditions}</p>
                        <div className="flex items-center justify-between mt-1.5">
                            <span className="text-xs font-semibold" style={{ color }}>
                                {r.recommended_action}
                            </span>
                            <span className="text-xs text-nkz-text-muted" title={r.source_model}>
                                {r.confidence === 'high' ? '📡' : '📡?'} {r.lwd_method ? `LWD: ${r.lwd_method}` : ''}
                            </span>
                        </div>
                    </div>
                );
            })}
        </div>
    );
};

export default DiseaseRiskWidget;
