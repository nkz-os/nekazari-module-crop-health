import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';

interface CropHealthAssessment {
    id: string;
    cwsiValue?: number;
    mdsValue?: number;
    mdsSeverity?: string;
    waterBalanceDeficit?: number;
    thermalCondition?: string;
    thermalSeverity?: string;
    vigorIndex?: number;
    vigorCondition?: string;
    compositeStressIndex?: number;
    dominantStressor?: string;
    yieldUtilizationPct?: number;
    yieldGapConfidence?: string;
    overallSeverity: string;
    recommendedAction: string;
    parcelId: string;
    parcelName?: string;
    assessedAt: string;
    phenologySource: string;
    dataFidelity?: string;
}

type ActionKey = 'NO_ACTION' | 'MONITOR' | 'IRRIGATE_SCHEDULED' | 'IRRIGATE_IMMEDIATE';

const ACTION_LABELS: Record<ActionKey, string> = {
    NO_ACTION: 'action.noAction',
    MONITOR: 'action.monitor',
    IRRIGATE_SCHEDULED: 'action.irrigateScheduled',
    IRRIGATE_IMMEDIATE: 'action.irrigateImmediate',
};

function SeverityBadge({ severity }: { severity: string }) {
    const classes: Record<string, string> = {
        LOW: 'bg-green-100 text-green-800 border border-green-200',
        MEDIUM: 'bg-amber-100 text-amber-800 border border-amber-200',
        HIGH: 'bg-orange-100 text-orange-800 border border-orange-200',
        CRITICAL: 'bg-red-100 text-red-800 border border-red-200',
    };
    const cls = classes[severity] || classes.LOW;
    return (
        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium leading-4 ${cls}`}>
            {severity}
        </span>
    );
}

function MiniProgress({ value, intent }: { value: number; intent: 'positive' | 'warning' | 'negative' }) {
    const barCls = intent === 'negative' ? 'bg-red-500' : intent === 'warning' ? 'bg-amber-500' : 'bg-green-500';
    return (
        <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                <div className={`h-full rounded-full transition-all ${barCls}`} style={{ width: `${Math.min(value, 100)}%` }} />
            </div>
            <span className="text-xs font-mono text-nkz-text-primary w-8 text-right">{Math.round(value)}%</span>
        </div>
    );
}

const CropHealthWidget: React.FC = () => {
    const { t } = useTranslation('crop-health');
    const [assessments, setAssessments] = useState<CropHealthAssessment[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchAssessments = async () => {
            try {
                const sdk = (window as any).__NKZ_SDK__;
                if (!sdk?.api) {
                    setError('SDK not available');
                    return;
                }
                const resp = await sdk.api.get('/api/crop-health/assessments/latest');
                if (resp.ok) {
                    const data = await resp.json();
                    setAssessments(data.assessments || []);
                } else {
                    setError(`HTTP ${resp.status}`);
                }
            } catch (e: any) {
                setError(e.message);
            } finally {
                setLoading(false);
            }
        };

        fetchAssessments();
        const interval = setInterval(fetchAssessments, 5 * 60 * 1000);
        return () => clearInterval(interval);
    }, []);

    if (loading) {
        return (
            <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-4">
                <div className="space-y-3">
                    <div className="animate-pulse h-20 bg-gray-100 rounded-lg" />
                    <div className="animate-pulse h-20 bg-gray-100 rounded-lg" />
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-4 text-center">
                <span className="text-2xl">⚠️</span>
                <p className="text-sm text-nkz-text-muted mt-1">{t('error')}: {error}</p>
            </div>
        );
    }

    if (assessments.length === 0) {
        return (
            <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-4 text-center">
                <span className="text-2xl">🌱</span>
                <p className="text-sm text-nkz-text-secondary mt-1">{t('noAssessments')}</p>
                <p className="text-xs text-nkz-text-muted mt-1">{t('noAssessmentsHint')}</p>
            </div>
        );
    }

    return (
        <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-3 space-y-3">
            {assessments.map((a) => {
                const sevColor = a.overallSeverity === 'CRITICAL' ? '#dc2626' : a.overallSeverity === 'HIGH' ? '#ea580c' : a.overallSeverity === 'MEDIUM' ? '#d97706' : '#16a34a';
                return (
                    <div key={a.id} className="bg-nkz-surface border border-nkz-border rounded-lg p-3">
                        {/* Header */}
                        <div className="flex items-center justify-between mb-2">
                            <button
                                className="text-sm font-semibold text-nkz-text-primary hover:text-nkz-accent-base transition-colors truncate"
                                onClick={() => { const sdk = (window as any).__NKZ_SDK__; if (sdk?.navigate) sdk.navigate('/entities'); }}
                                title="View in 3D viewer"
                            >
                                {a.parcelName || a.parcelId}
                            </button>
                            <SeverityBadge severity={a.overallSeverity} />
                        </div>

                        {/* Metrics grid */}
                        <div className="grid grid-cols-2 gap-2">
                            {a.cwsiValue !== undefined && (
                                <div>
                                    <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">CWSI</span>
                                    <MiniProgress value={a.cwsiValue * 100} intent={a.cwsiValue > 0.6 ? 'negative' : a.cwsiValue > 0.3 ? 'warning' : 'positive'} />
                                </div>
                            )}
                            {a.compositeStressIndex !== undefined && (
                                <div>
                                    <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">Stress</span>
                                    <MiniProgress value={a.compositeStressIndex} intent={a.compositeStressIndex > 75 ? 'negative' : a.compositeStressIndex > 50 ? 'warning' : 'positive'} />
                                </div>
                            )}
                            {a.vigorIndex !== undefined && (
                                <div>
                                    <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">{t('vigor')}</span>
                                    <MiniProgress value={a.vigorIndex * 100} intent={a.vigorIndex > 0.6 ? 'positive' : a.vigorIndex > 0.3 ? 'warning' : 'negative'} />
                                </div>
                            )}
                            {a.yieldUtilizationPct !== undefined && (
                                <div>
                                    <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">Yield</span>
                                    <MiniProgress value={a.yieldUtilizationPct} intent={a.yieldUtilizationPct > 80 ? 'positive' : a.yieldUtilizationPct > 60 ? 'warning' : 'negative'} />
                                </div>
                            )}
                            {a.mdsSeverity && a.mdsValue !== undefined && (
                                <div>
                                    <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">MDS</span>
                                    <div className="flex items-center gap-1 mt-1">
                                        <span className="text-sm font-mono text-nkz-text-primary">{a.mdsValue.toFixed(0)}µm</span>
                                        <SeverityBadge severity={a.mdsSeverity} />
                                    </div>
                                </div>
                            )}
                            {a.waterBalanceDeficit !== undefined && (
                                <div>
                                    <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">{t('waterBalance')}</span>
                                    <div className="mt-1">
                                        <span className={`text-sm font-mono ${a.waterBalanceDeficit < 0 ? 'text-red-500' : 'text-green-500'}`}>
                                            {a.waterBalanceDeficit > 0 ? '+' : ''}{a.waterBalanceDeficit.toFixed(1)}mm
                                        </span>
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Action footer */}
                        <div className="flex items-center justify-between mt-2 pt-2 border-t border-nkz-border">
                            <span className="text-xs font-semibold" style={{ color: sevColor }}>
                                {t(ACTION_LABELS[a.recommendedAction as ActionKey] || a.recommendedAction)}
                            </span>
                            <span className="text-xs text-nkz-text-muted">
                                {a.phenologySource === 'bioorchestrator' ? '📚 BioOrchestrator' : '📋 ' + t('defaultParams')}
                            </span>
                        </div>

                        {a.assessedAt && (
                            <p className="text-xs text-nkz-text-muted mt-1">{new Date(a.assessedAt).toLocaleString()}</p>
                        )}
                    </div>
                );
            })}
        </div>
    );
};

export default CropHealthWidget;
