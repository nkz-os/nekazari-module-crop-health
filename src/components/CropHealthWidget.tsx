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
    overallSeverity: string;
    recommendedAction: string;
    parcelId: string;
    parcelName?: string;
    assessedAt: string;
    phenologySource: string;
    dataFidelity?: string;
}

type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

const SEVERITY_COLORS: Record<Severity, string> = {
    LOW: '#16a34a',
    MEDIUM: '#d97706',
    HIGH: '#ea580c',
    CRITICAL: '#dc2626',
};

const SEVERITY_I18N: Record<Severity, string> = {
    LOW: 'LOW',
    MEDIUM: 'MEDIUM',
    HIGH: 'HIGH',
    CRITICAL: 'CRITICAL',
};

const ACTION_LABELS: Record<string, string> = {
    NO_ACTION: 'noAction',
    MONITOR: 'monitor',
    IRRIGATE_SCHEDULED: 'irrigateScheduled',
    IRRIGATE_IMMEDIATE: 'irrigateImmediate',
};

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
        return <div className="chw-loading">{t('loading')}</div>;
    }

    if (error) {
        return <div className="chw-error">{t('error')}: {error}</div>;
    }

    if (assessments.length === 0) {
        return (
            <div className="chw-empty">
                <span className="chw-empty-icon">🌱</span>
                <p>{t('noAssessments')}</p>
                <p className="chw-empty-hint">{t('noAssessmentsHint')}</p>
            </div>
        );
    }

    return (
        <div className="chw-container">
            <h3 className="chw-title">{t('title')}</h3>
            {assessments.map((a) => (
                <div key={a.id} className="chw-card">
                    <div className="chw-card-header">
                        <a
                            className="chw-parcel"
                            href={`/entities`}
                            onClick={(e) => {
                                e.preventDefault();
                                const sdk = (window as any).__NKZ_SDK__;
                                if (sdk?.navigate) sdk.navigate('/entities');
                            }}
                            title="Ver en el visor 3D"
                        >
                            {a.parcelName || a.parcelId}
                        </a>
                        <span
                            className="chw-severity"
                            style={{ background: SEVERITY_COLORS[a.overallSeverity as Severity] || '#6b7280' }}
                        >
                            {t(`severity.${SEVERITY_I18N[a.overallSeverity as Severity] || a.overallSeverity}`)}
                        </span>
                    </div>

                    <div className="chw-metrics">
                        {a.cwsiValue !== undefined && (
                            <div className="chw-metric">
                                <span className="chw-metric-label">CWSI</span>
                                <div className="chw-bar">
                                    <div
                                        className="chw-bar-fill"
                                        style={{
                                            width: `${Math.min(a.cwsiValue * 100, 100)}%`,
                                            background: a.cwsiValue > 0.6 ? '#dc2626' : a.cwsiValue > 0.3 ? '#d97706' : '#16a34a',
                                        }}
                                    />
                                </div>
                                <span className="chw-metric-value">{a.cwsiValue.toFixed(2)}</span>
                            </div>
                        )}

                        {a.mdsSeverity && (
                            <div className="chw-metric">
                                <span className="chw-metric-label">MDS</span>
                                <span
                                    className="chw-metric-badge"
                                    style={{ background: SEVERITY_COLORS[a.mdsSeverity as Severity] || '#6b7280' }}
                                >
                                    {a.mdsSeverity}
                                </span>
                                {a.mdsValue !== undefined && (
                                    <span className="chw-metric-value">{a.mdsValue.toFixed(0)}µm</span>
                                )}
                            </div>
                        )}

                        {a.waterBalanceDeficit !== undefined && (
                            <div className="chw-metric">
                                <span className="chw-metric-label">{t('waterBalance')}</span>
                                <span className={`chw-metric-value ${a.waterBalanceDeficit < 0 ? 'chw-deficit' : 'chw-surplus'}`}>
                                    {a.waterBalanceDeficit > 0 ? '+' : ''}{a.waterBalanceDeficit.toFixed(1)}mm
                                </span>
                            </div>
                        )}
                        {a.thermalCondition && a.thermalCondition !== 'no_stress' && (
                            <div className="chw-metric">
                                <span className="chw-metric-label">{t('thermal')}</span>
                                <span className="chw-metric-badge" style={{
                                    background: a.thermalSeverity === 'CRITICAL' ? '#fee2e2' : '#fef3c7',
                                    color: a.thermalSeverity === 'CRITICAL' ? '#991b1b' : '#92400e',
                                }}>
                                    {a.thermalCondition?.startsWith('frost') ? '❄️' : '🔥'} {a.thermalSeverity}
                                </span>
                            </div>
                        )}
                        {a.vigorIndex !== undefined && (
                            <div className="chw-metric">
                                <span className="chw-metric-label">{t('vigor')}</span>
                                <div className="chw-bar">
                                    <div className="chw-bar-fill" style={{
                                        width: `${a.vigorIndex * 100}%`,
                                        background: a.vigorIndex > 0.6 ? '#16a34a' : a.vigorIndex > 0.3 ? '#d97706' : '#dc2626',
                                    }} />
                                </div>
                                <span className="chw-metric-value">{a.vigorIndex.toFixed(2)}</span>
                            </div>
                        )}
                    </div>

                    <div className="chw-footer">
                        <span className="chw-action" style={{ color: SEVERITY_COLORS[a.overallSeverity as Severity] || '#6b7280' }}>
                            {t(`action.${ACTION_LABELS[a.recommendedAction] || a.recommendedAction}`)}
                        </span>
                        <a
                            className="chw-source"
                            href="/bioorchestrator"
                            onClick={(e) => {
                                e.preventDefault();
                                const sdk = (window as any).__NKZ_SDK__;
                                if (sdk?.navigate) sdk.navigate('/bioorchestrator?tab=phenology');
                            }}
                            title="Ver parámetros en BioOrchestrator"
                        >
                            {a.phenologySource === 'bioorchestrator' ? '📚 BioOrchestrator' : '📋 ' + t('defaultParams')}
                        </a>
                    </div>
                    <div className="chw-updated">
                        {a.assessedAt ? new Date(a.assessedAt).toLocaleString() : ''}
                    </div>
                </div>
            ))}
        </div>
    );
};

export default CropHealthWidget;
