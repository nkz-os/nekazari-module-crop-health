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

const CropHealthWidget: React.FC = () => {
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

    if (loading) return null;
    if (!risks.length) return null;

    const active = risks.filter(r => r.risk_level !== 'LOW');
    if (!active.length) return null;

    return (
        <div className="chw-container">
            <h3 className="chw-title">🦠 {t('diseaseRisk')}</h3>
            {active.map((r, i) => (
                <div key={i} className="chw-card" style={{ borderLeftColor: RISK_COLORS[r.risk_level] || '#6b7280' }}>
                    <div className="chw-card-header">
                        <span className="chw-parcel">{DISEASE_LABELS[r.disease] || r.disease}</span>
                        <span className="chw-severity" style={{
                            background: r.risk_level === 'HIGH' ? '#fee2e2' : '#fef3c7',
                            color: r.risk_level === 'HIGH' ? '#991b1b' : '#92400e',
                        }}>{r.risk_level}</span>
                    </div>
                    <div className="chw-metrics">
                        <p className="chw-disease-conditions">{r.conditions}</p>
                        <p className="chw-disease-action" style={{ color: RISK_COLORS[r.risk_level] }}>
                            {r.recommended_action}
                        </p>
                    </div>
                    <div className="chw-footer">
                        <span className="chw-source" title={r.source_model}>
                            {r.confidence === 'high' ? '📡' : '📡?'} {r.lwd_method ? `LWD: ${r.lwd_method}` : ''}
                        </span>
                    </div>
                </div>
            ))}
        </div>
    );
};

export default CropHealthWidget;
