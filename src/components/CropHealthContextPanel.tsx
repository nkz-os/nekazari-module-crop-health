import React, { useEffect, useState } from 'react';

interface PhenologyData {
    kc?: number;
    d1?: number;
    d2?: number;
    mds_ref?: number;
    match_level?: string;
    provenance?: {
        short?: string;
        doi?: string;
        author?: string;
        year?: number;
        conditions?: string;
    };
}

interface TrendPoint {
    date: string;
    cwsi?: number;
    mds?: number;
    balance?: number;
}

interface CorrelationData {
    date: string;
    ndvi?: number;
    cwsi?: number;
}

interface AssessmentData {
    cwsiValue?: number;
    mdsValue?: number;
    mdsSeverity?: string;
    waterBalanceDeficit?: number;
    overallSeverity: string;
    recommendedAction: string;
    phenologySource: string;
    assessedAt: string;
    compositeStressIndex?: number;
    dominantStressor?: string;
    yieldUtilizationPct?: number;
    yieldGapConfidence?: string;
    thermalCondition?: string;
    thermalSeverity?: string;
    vigorIndex?: number;
    vigorCondition?: string;
    dataFidelity?: string;
}

type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

const SEVERITY_COLORS: Record<Severity, { bg: string; text: string; border: string }> = {
    LOW: { bg: '#dcfce7', text: '#166534', border: '#16a34a' },
    MEDIUM: { bg: '#fef3c7', text: '#92400e', border: '#d97706' },
    HIGH: { bg: '#fed7aa', text: '#9a3412', border: '#ea580c' },
    CRITICAL: { bg: '#fee2e2', text: '#991b1b', border: '#dc2626' },
};

const Sparkline: React.FC<{ data: number[]; color: string; width?: number; height?: number }> = ({
    data, color, width = 80, height = 24,
}) => {
    const w = width, h = height, pad = 2;
    const max = Math.max(...data, 0.01);
    const min = Math.min(...data, 0);
    const range = max - min || 1;
    const points = data.map((v, i) => {
        const x = pad + (i / (data.length - 1)) * (w - pad * 2);
        const y = pad + ((max - v) / range) * (h - pad * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return (
        <svg width={w} height={h} className="inline-block align-middle ml-2">
            <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
    );
};

interface Props {
    parcelId: string;
    parcelName?: string;
    onOpenPhenology?: (species: string) => void;
}

const CropHealthContextPanel: React.FC<Props> = ({ parcelId, parcelName, onOpenPhenology }) => {
    const [assessment, setAssessment] = useState<AssessmentData | null>(null);
    const [phenology, setPhenology] = useState<PhenologyData | null>(null);
    const [trend, setTrend] = useState<TrendPoint[]>([]);
    const [correlation, setCorrelation] = useState<CorrelationData[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!parcelId) return;
        setLoading(true);

        const fetchData = async () => {
            try {
                const base = '/api/crop-health';
                const [aRes, tRes, cRes] = await Promise.allSettled([
                    fetch(`${base}/assessments/latest?parcelId=${parcelId}`).then(r => r.ok ? r.json() : null),
                    fetch(`${base}/assessments/history?parcelId=${parcelId}&days=7`).then(r => r.ok ? r.json() : null),
                    fetch(`${base}/assessments/correlation?parcelId=${parcelId}&days=30`).then(r => r.ok ? r.json() : null),
                ]);

                if (aRes.status === 'fulfilled' && aRes.value?.assessments?.[0]) {
                    setAssessment(aRes.value.assessments[0]);
                }
                if (tRes.status === 'fulfilled' && tRes.value?.points) {
                    setTrend(tRes.value.points);
                }
                if (cRes.status === 'fulfilled' && cRes.value?.pairs) {
                    setCorrelation(cRes.value.pairs);
                }

                // Fetch phenology if we have species info
                const a = aRes.status === 'fulfilled' ? aRes.value?.assessments?.[0] : null;
                if (a?.species) {
                    try {
                        const pResp = await fetch(
                            `/api/bioorchestrator/api/graph/phenology-params?species=${encodeURIComponent(a.species)}`
                        );
                        if (pResp.ok) setPhenology(await pResp.json());
                    } catch { /* phenology optional */ }
                }
            } catch { /* handle gracefully */ }
            finally { setLoading(false); }
        };

        fetchData();
    }, [parcelId]);

    if (loading) {
        return <div className="chp-loading">Cargando salud del cultivo...</div>;
    }

    if (!assessment) {
        return (
            <div className="chp-empty">
                <span>🌱</span>
                <p>Sin datos de salud para esta parcela</p>
                <p className="chp-hint">Conecta sensores IR o dendrómetros para ver CWSI y MDS</p>
            </div>
        );
    }

    const sev = SEVERITY_COLORS[assessment.overallSeverity as Severity] || SEVERITY_COLORS.LOW;
    const trendCW = trend.filter(p => p.cwsi != null).map(p => p.cwsi!);
    const trendMDS = trend.filter(p => p.mds != null).map(p => p.mds!);
    const trendDir = trendCW.length >= 2 ? (trendCW[trendCW.length - 1] - trendCW[0]).toFixed(2) : null;
    const actionLabels: Record<string, string> = {
        NO_ACTION: 'Sin acción necesaria',
        MONITOR: 'Monitorizar evolución',
        IRRIGATE_SCHEDULED: 'Programar riego',
        IRRIGATE_IMMEDIATE: 'Regar inmediatamente',
    };

    return (
        <div className="chp-container">
            {/* Header */}
            <div className="chp-header" style={{ borderLeftColor: sev.border }}>
                <h3>{parcelName || parcelId}</h3>
                <span className="chp-severity" style={{ background: sev.bg, color: sev.text, borderColor: sev.border }}>
                    {assessment.overallSeverity}
                </span>
            </div>

            {/* CWSI */}
            {assessment.cwsiValue != null && (
                <div className="chp-section">
                    <div className="chp-section-header">
                        <span>CWSI — Índice de Estrés Hídrico</span>
                        {trendCW.length >= 2 && <Sparkline data={trendCW} color="#dc2626" />}
                    </div>
                    <div className="chp-gauge">
                        <div className="chp-gauge-track">
                            <div className="chp-gauge-fill"
                                style={{
                                    width: `${Math.min(assessment.cwsiValue * 100, 100)}%`,
                                    background: assessment.cwsiValue > 0.6 ? '#dc2626' : assessment.cwsiValue > 0.3 ? '#d97706' : '#16a34a',
                                }}
                            />
                        </div>
                        <span className="chp-gauge-value">{assessment.cwsiValue.toFixed(2)}</span>
                    </div>
                    {trendDir && (
                        <p className="chp-trend" style={{ color: Number(trendDir) > 0 ? '#dc2626' : '#16a34a' }}>
                            {Number(trendDir) > 0 ? '↑' : '↓'} {Math.abs(Number(trendDir))} en 7 días
                            {Number(trendDir) > 0.05 ? ' — empeorando' : Number(trendDir) < -0.05 ? ' — mejorando' : ' — estable'}
                        </p>
                    )}
                </div>
            )}

            {/* MDS */}
            {assessment.mdsValue != null && (
                <div className="chp-section">
                    <div className="chp-section-header">
                        <span>MDS — Contracción Máxima Diaria</span>
                        {trendMDS.length >= 2 && <Sparkline data={trendMDS} color="#7c3aed" />}
                    </div>
                    <div className="chp-metric-row">
                        <span className="chp-metric-value">{assessment.mdsValue.toFixed(0)}µm</span>
                        {assessment.mdsSeverity && (
                            <span className="chp-metric-badge" style={{
                                background: SEVERITY_COLORS[assessment.mdsSeverity as Severity]?.bg,
                                color: SEVERITY_COLORS[assessment.mdsSeverity as Severity]?.text,
                            }}>
                                {assessment.mdsSeverity}
                            </span>
                        )}
                    </div>
                </div>
            )}

            {/* Water Balance */}
            {assessment.waterBalanceDeficit != null && (
                <div className="chp-section">
                    <div className="chp-section-header">Balance Hídrico</div>
                    <div className="chp-metric-row">
                        <span className={`chp-metric-value ${assessment.waterBalanceDeficit < 0 ? 'chp-deficit' : 'chp-surplus'}`}
                            style={{ color: assessment.waterBalanceDeficit < 0 ? '#dc2626' : '#16a34a' }}>
                            {assessment.waterBalanceDeficit > 0 ? '+' : ''}{assessment.waterBalanceDeficit.toFixed(1)}mm
                        </span>
                    </div>
                </div>
            )}

            {/* Phenology */}
            {phenology && (
                <div className="chp-section chp-phenology">
                    <div className="chp-section-header">Parámetros Fenológicos</div>
                    <div className="chp-params-grid">
                        <div className="chp-param"><span>Kc</span><strong>{phenology.kc?.toFixed(2)}</strong></div>
                        <div className="chp-param"><span>D1</span><strong>{phenology.d1?.toFixed(1)}°C</strong></div>
                        <div className="chp-param"><span>D2</span><strong>{phenology.d2?.toFixed(1)}°C</strong></div>
                        <div className="chp-param"><span>MDS ref</span><strong>{phenology.mds_ref?.toFixed(0)}µm</strong></div>
                    </div>
                    {phenology.provenance && (
                        <p className="chp-provenance">
                            📚 {phenology.provenance.short}
                            {phenology.provenance.author && ` — ${phenology.provenance.author}`}
                            {phenology.provenance.year && ` (${phenology.provenance.year})`}
                            {phenology.provenance.doi && (
                                <> · <a href={`https://doi.org/${phenology.provenance.doi}`} target="_blank" rel="noopener" className="chp-doi">DOI</a></>
                            )}
                        </p>
                    )}
                    <p className="chp-match">Coincidencia: <strong>{phenology.match_level?.toUpperCase()}</strong></p>
                </div>
            )}

            {/* Composite Stress */}
            {assessment.compositeStressIndex != null && (
                <div className="chp-section">
                    <div className="chp-section-header">Estrés Compuesto (ponderado FAO-33)</div>
                    <div className="chp-gauge">
                        <div className="chp-gauge-track">
                            <div className="chp-gauge-fill" style={{
                                width: `${Math.min(assessment.compositeStressIndex, 100)}%`,
                                background: assessment.compositeStressIndex > 75 ? '#dc2626' : assessment.compositeStressIndex > 50 ? '#d97706' : '#16a34a',
                            }} />
                        </div>
                        <span className="chp-gauge-value">{assessment.compositeStressIndex?.toFixed(0)}/100</span>
                    </div>
                    {assessment.dominantStressor && assessment.dominantStressor !== 'none' && (
                        <p className="chp-trend">Dominante: <strong>{assessment.dominantStressor}</strong></p>
                    )}
                </div>
            )}

            {/* Yield Gap */}
            {assessment.yieldUtilizationPct != null && (
                <div className="chp-section">
                    <div className="chp-section-header">Aprovechamiento de Potencial (Yield Gap FAO-33)</div>
                    <div className="chp-gauge">
                        <div className="chp-gauge-track">
                            <div className="chp-gauge-fill" style={{
                                width: `${Math.min(assessment.yieldUtilizationPct, 100)}%`,
                                background: assessment.yieldUtilizationPct > 80 ? '#16a34a' : assessment.yieldUtilizationPct > 60 ? '#d97706' : '#dc2626',
                            }} />
                        </div>
                        <span className="chp-gauge-value">{assessment.yieldUtilizationPct?.toFixed(0)}%</span>
                    </div>
                    <p className="chp-trend" style={{ color: '#6b7280', fontSize: '0.75rem' }}>
                        {assessment.yieldGapConfidence === 'high' ? '📡 Alta confianza' :
                         assessment.yieldGapConfidence === 'medium' ? '📡? Confianza media' :
                         '📡? Baja confianza'} · NO es predicción de cosecha
                    </p>
                </div>
            )}

            {/* Data Fidelity */}
            {assessment.dataFidelity && (
                <div className="chp-section">
                    <div className="chp-section-header">Fidelidad de Datos</div>
                    <span className="chp-fidelity-badge" style={{
                        background: assessment.dataFidelity === 'onsite_calibrated' ? '#dcfce7' :
                                    assessment.dataFidelity === 'onsite_uncalibrated' ? '#fef3c7' : '#e0e7ff',
                        color: assessment.dataFidelity === 'onsite_calibrated' ? '#166534' :
                               assessment.dataFidelity === 'onsite_uncalibrated' ? '#92400e' : '#3730a3',
                        padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem',
                    }}>
                        {assessment.dataFidelity}
                    </span>
                </div>
            )}

            {/* Correlation */}
            {correlation.length >= 3 && (
                <div className="chp-section">
                    <div className="chp-section-header">Correlación NDVI (satélite) vs CWSI (suelo)</div>
                    <div className="chp-correlation">
                        {correlation.slice(-5).map((p, i) => (
                            <div key={i} className="chp-corr-row">
                                <span className="chp-corr-date">{p.date?.slice(0, 10)}</span>
                                <span className="chp-corr-ndvi" style={{ color: (p.ndvi || 0) > 0.5 ? '#16a34a' : '#d97706' }}>
                                    NDVI {(p.ndvi || 0).toFixed(2)}
                                </span>
                                <span className="chp-corr-cwsi" style={{ color: (p.cwsi || 0) > 0.5 ? '#dc2626' : '#16a34a' }}>
                                    CWSI {(p.cwsi || 0).toFixed(2)}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Recommendation */}
            <div className="chp-action" style={{ background: sev.bg, borderColor: sev.border }}>
                <span className="chp-action-icon">
                    {assessment.overallSeverity === 'CRITICAL' ? '🔴' : assessment.overallSeverity === 'HIGH' ? '🟠' : assessment.overallSeverity === 'MEDIUM' ? '🟡' : '🟢'}
                </span>
                <div>
                    <strong>{actionLabels[assessment.recommendedAction] || assessment.recommendedAction}</strong>
                    <p className="chp-action-justify">
                        {assessment.cwsiValue != null && assessment.cwsiValue > 0.6 && 'CWSI elevado. '}
                        {assessment.mdsSeverity === 'CRITICAL' && 'Contracción del tronco crítica. '}
                        {assessment.waterBalanceDeficit != null && assessment.waterBalanceDeficit < -5 && 'Déficit hídrico significativo. '}
                        Basado en {assessment.phenologySource === 'bioorchestrator' ? 'parámetros fenológicos específicos' : 'parámetros genéricos'}.
                    </p>
                </div>
            </div>

            {/* Footer */}
            <p className="chp-footer">
                Actualizado: {assessment.assessedAt ? new Date(assessment.assessedAt).toLocaleString() : 'desconocido'}
                {' · '}
                <a href={`/api/crop-health/assessments/export?parcelId=${parcelId}&days=30`}
                   className="chp-export-link" download>
                    📥 Exportar CSV
                </a>
            </p>
        </div>
    );
};

export default CropHealthContextPanel;
