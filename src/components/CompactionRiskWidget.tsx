import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';

interface CompactionRiskData {
    riskLevel: string;
    riskScore: number;
    susceptibilityScore: number;
    contributingFactors: string[];
    moistureWarning: boolean;
    vigorConcern: boolean;
    requiresFieldVerification: boolean;
    advisory: string;
    parcelId: string;
    parcelName?: string;
}

const RISK_COLORS: Record<string, string> = {
    low: '#16a34a',
    moderate: '#d97706',
    high: '#ea580c',
    very_high: '#dc2626',
};

const RISK_BG: Record<string, string> = {
    low: '#dcfce7',
    moderate: '#fef3c7',
    high: '#ffedd5',
    very_high: '#fee2e2',
};

const FACTOR_ICONS: Record<string, string> = {
    wet_soil_on_susceptible_ground: '💧🚜',
    wet_soil: '💧',
    moist_soil_susceptible: '🌧️',
    persistent_low_vigor: '📉',
    mild_persistent_low_vigor: '📊',
    high_traffic_exposure: '🔄',
    moderate_traffic_exposure: '↔️',
    indicative_elevated_bd: '📏',
};

function factorIcon(factor: string): string {
    for (const [prefix, icon] of Object.entries(FACTOR_ICONS)) {
        if (factor.startsWith(prefix)) return icon;
    }
    return '•';
}

function factorLabel(factor: string, t: (key: string) => string): string {
    const key = `factor.${factor.replace(/_\d+y$/, '').replace(/_\d+$/, '')}`;
    const translated = t(key);
    if (translated !== key) return translated;
    return factor.replace(/_/g, ' ');
}

const CompactionRiskWidget: React.FC = () => {
    const { t } = useTranslation('crop-health');
    const [risks, setRisks] = useState<CompactionRiskData[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchRisks = async () => {
            try {
                const sdk = (window as any).__NKZ_SDK__;
                if (!sdk?.api) { setError('SDK not available'); return; }
                const resp = await sdk.api.get('/api/crop-health/assessments/latest');
                if (resp.ok) {
                    const data = await resp.json();
                    const assessments = data.assessments || [];
                    const compactionRisks: CompactionRiskData[] = assessments
                        .filter((a: any) => a.compactionRiskLevel)
                        .map((a: any) => ({
                            riskLevel: a.compactionRiskLevel,
                            riskScore: a.compactionRiskScore ?? 0,
                            susceptibilityScore: a.susceptibilityScore ?? 0,
                            contributingFactors: a.compactionRiskFactors ?? [],
                            moistureWarning: a.compactionMoistureWarning ?? false,
                            vigorConcern: a.compactionVigorConcern ?? false,
                            requiresFieldVerification: a.compactionRequiresVerification ?? true,
                            advisory: a.advisory ?? '',
                            parcelId: a.parcelId,
                            parcelName: a.parcelName,
                        }));
                    setRisks(compactionRisks);
                } else {
                    setError(`HTTP ${resp.status}`);
                }
            } catch (e: any) {
                setError(e.message);
            } finally {
                setLoading(false);
            }
        };

        fetchRisks();
        const interval = setInterval(fetchRisks, 5 * 60 * 1000);
        return () => clearInterval(interval);
    }, []);

    if (loading) return null;
    if (error) return null; // silent — compaction is advisory, don't bother user with errors
    if (!risks.length) return null; // no compaction data = nothing to show

    return (
        <div className="chw-container">
            <h3 className="chw-title">🪨 {t('compaction.title')}</h3>
            {risks.map((r, i) => (
                <div
                    key={i}
                    className="chw-card"
                    style={{
                        borderLeft: `4px solid ${RISK_COLORS[r.riskLevel] || '#6b7280'}`,
                    }}
                >
                    <div className="chw-card-header">
                        <a
                            className="chw-parcel"
                            href="/entities"
                            onClick={(e) => {
                                e.preventDefault();
                                const sdk = (window as any).__NKZ_SDK__;
                                if (sdk?.navigate) sdk.navigate('/entities');
                            }}
                        >
                            {r.parcelName || r.parcelId}
                        </a>
                        <span
                            className="chw-severity"
                            style={{
                                background: RISK_BG[r.riskLevel] || '#f3f4f6',
                                color: RISK_COLORS[r.riskLevel] || '#6b7280',
                            }}
                        >
                            {t(`compaction.level.${r.riskLevel}`)}
                        </span>
                    </div>

                    {/* Risk score bar */}
                    <div className="chw-metrics">
                        <div className="chw-metric">
                            <span className="chw-metric-label">{t('compaction.riskScore')}</span>
                            <div className="chw-bar">
                                <div
                                    className="chw-bar-fill"
                                    style={{
                                        width: `${Math.min(r.riskScore, 100)}%`,
                                        background: RISK_COLORS[r.riskLevel] || '#6b7280',
                                    }}
                                />
                            </div>
                            <span className="chw-metric-value">{r.riskScore.toFixed(0)}%</span>
                        </div>
                    </div>

                    {/* Contributing factors */}
                    {r.contributingFactors.length > 0 && (
                        <div className="chw-metrics">
                            {r.contributingFactors.map((f, j) => (
                                <div key={j} className="chw-metric" style={{ flexBasis: '100%' }}>
                                    <span style={{ marginRight: 6 }}>{factorIcon(f)}</span>
                                    <span className="chw-metric-label" style={{ fontSize: '0.8rem' }}>
                                        {factorLabel(f, t)}
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Advisory */}
                    <div className="chw-footer">
                        <span
                            className="chw-action"
                            style={{ color: RISK_COLORS[r.riskLevel] || '#6b7280' }}
                        >
                            {r.moistureWarning && '⚠️ '}
                            {r.vigorConcern && '🔍 '}
                            {t(`compaction.advisory.${r.advisory || 'normal_management'}`, r.advisory || '')}
                        </span>
                        {r.requiresFieldVerification && (
                            <span className="chw-source" title={t('compaction.verifyHint')}>
                                📋 {t('compaction.verifyInField')}
                            </span>
                        )}
                    </div>
                </div>
            ))}
        </div>
    );
};

export default CompactionRiskWidget;
