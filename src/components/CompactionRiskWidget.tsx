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

const RISK_BADGE: Record<string, string> = {
    low: 'bg-green-100 text-green-800 border border-green-200',
    moderate: 'bg-amber-100 text-amber-800 border border-amber-200',
    high: 'bg-orange-100 text-orange-800 border border-orange-200',
    very_high: 'bg-red-100 text-red-800 border border-red-200',
};

const RISK_COLORS: Record<string, string> = {
    low: '#16a34a',
    moderate: '#d97706',
    high: '#ea580c',
    very_high: '#dc2626',
};

const RISK_BAR: Record<string, string> = {
    low: 'bg-green-500',
    moderate: 'bg-amber-500',
    high: 'bg-orange-500',
    very_high: 'bg-red-500',
};

const FACTOR_EMOJIS: Record<string, string> = {
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
    for (const [prefix, icon] of Object.entries(FACTOR_EMOJIS)) {
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
    if (error) return null;
    if (!risks.length) return null;

    return (
        <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-3 space-y-2">
            <div className="flex items-center gap-2 mb-1">
                <span className="text-base">🪨</span>
                <span className="text-sm font-semibold text-nkz-text-primary">{t('compaction.title')}</span>
            </div>
            {risks.map((r, i) => {
                const color = RISK_COLORS[r.riskLevel] || '#6b7280';
                const barCls = RISK_BAR[r.riskLevel] || 'bg-gray-500';
                return (
                    <div key={i} className="bg-nkz-surface border border-nkz-border rounded-lg p-2.5 border-l-[3px]" style={{ borderLeftColor: color }}>
                        {/* Header */}
                        <div className="flex items-center justify-between">
                            <button
                                className="text-sm font-semibold text-nkz-text-primary hover:text-nkz-accent-base transition-colors truncate"
                                onClick={() => { const sdk = (window as any).__NKZ_SDK__; if (sdk?.navigate) sdk.navigate('/entities'); }}
                            >
                                {r.parcelName || r.parcelId}
                            </button>
                            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium leading-4 ${RISK_BADGE[r.riskLevel] || 'bg-gray-100 text-gray-800'}`}>
                                {t(`compaction.level.${r.riskLevel}`)}
                            </span>
                        </div>

                        {/* Risk score bar */}
                        <div className="mt-2">
                            <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">{t('compaction.riskScore')}</span>
                            <div className="flex items-center gap-2 mt-0.5">
                                <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                                    <div className={`h-full rounded-full transition-all ${barCls}`} style={{ width: `${Math.min(r.riskScore, 100)}%` }} />
                                </div>
                                <span className="text-xs font-mono text-nkz-text-primary">{r.riskScore.toFixed(0)}%</span>
                            </div>
                        </div>

                        {/* Contributing factors */}
                        {r.contributingFactors.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1.5">
                                {r.contributingFactors.map((f, j) => (
                                    <span key={j} className="text-xs text-nkz-text-muted bg-nkz-surface-sunken px-2 py-0.5 rounded" title={factorLabel(f, t)}>
                                        {factorIcon(f)} {factorLabel(f, t)}
                                    </span>
                                ))}
                            </div>
                        )}

                        {/* Advisory & verification */}
                        <div className="flex items-center justify-between mt-1.5 pt-1.5 border-t border-nkz-border">
                            <span className="text-xs" style={{ color }}>
                                {r.moistureWarning && '⚠️ '}
                                {r.vigorConcern && '🔍 '}
                                {t(`compaction.advisory.${r.advisory || 'normal_management'}`, r.advisory || '')}
                            </span>
                            {r.requiresFieldVerification && (
                                <span className="text-xs text-nkz-text-muted cursor-help" title={t('compaction.verifyHint')}>
                                    📋 {t('compaction.verifyInField')}
                                </span>
                            )}
                        </div>
                    </div>
                );
            })}
        </div>
    );
};

export default CompactionRiskWidget;
