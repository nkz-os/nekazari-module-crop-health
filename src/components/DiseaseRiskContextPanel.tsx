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

const RISK_COLORS: Record<string, string> = {
    LOW: '#16a34a',
    MEDIUM: '#d97706',
    HIGH: '#dc2626',
};

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

    if (loading) {
        return <div className="chp-loading">{t('contextPanel.loading')}</div>;
    }

    if (!risks.length) {
        return (
            <div className="chp-empty">
                <span>🛡️</span>
                <p>{t('diseaseRiskNone')}</p>
            </div>
        );
    }

    return (
        <div className="chp-container">
            <div className="chp-header" style={{ borderLeftColor: '#d97706' }}>
                <h3>🦠 {t('diseaseRisk')}{parcelName ? ` — ${parcelName}` : ''}</h3>
            </div>
            {risks.map((r, i) => (
                <div key={i} className="chp-section" style={{ borderLeft: `3px solid ${RISK_COLORS[r.risk_level] || '#6b7280'}`, paddingLeft: '8px' }}>
                    <div className="chp-section-header">
                        <span>{DISEASE_LABELS[r.disease] || r.disease}</span>
                        <span className="chp-metric-badge" style={{
                            background: r.risk_level === 'HIGH' ? '#fee2e2' : r.risk_level === 'MEDIUM' ? '#fef3c7' : '#dcfce7',
                            color: r.risk_level === 'HIGH' ? '#991b1b' : r.risk_level === 'MEDIUM' ? '#92400e' : '#166534',
                            padding: '1px 6px', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 600,
                        }}>{r.risk_level}</span>
                    </div>
                    {r.crop && <p className="chp-trend">🌾 {r.crop}</p>}
                    <p className="chp-trend">{r.conditions}</p>
                    <p className="chp-trend" style={{ color: RISK_COLORS[r.risk_level], fontWeight: 600 }}>
                        {r.recommended_action}
                    </p>
                    <div style={{ fontSize: '0.7rem', color: '#6b7280', marginTop: '4px' }}>
                        {r.confidence && `${r.confidence} confidence`}
                        {r.lwd_method && ` · LWD: ${r.lwd_method}`}
                        {r.source_model && ` · ${r.source_model}`}
                    </div>
                </div>
            ))}
        </div>
    );
};

export default DiseaseRiskContextPanel;
