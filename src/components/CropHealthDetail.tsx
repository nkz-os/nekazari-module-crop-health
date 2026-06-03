import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Sparkline } from './shared/Sparkline';
import { SeverityBadge, SEVERITY_STYLES } from './shared/SeverityBadge';

interface PhenologyData {
  kc?: number;
  d1?: number;
  d2?: number;
  mds_ref?: number;
  match_level?: string;
  stage?: string;
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
  wueStatus?: string;
  wueKgM3?: number;
  wueBiomassKg?: number;
  wueWaterAppliedMm?: number;
  wueTrend?: string;
  species?: string;
}

interface CropHealthDetailProps {
  parcelId: string;
}

const actionLabels: Record<string, string> = {
  NO_ACTION: 'contextPanel.noAction',
  MONITOR: 'contextPanel.monitorEvolution',
  IRRIGATE_SCHEDULED: 'contextPanel.scheduleIrrigation',
  IRRIGATE_IMMEDIATE: 'contextPanel.irrigateImmediately',
};

const CropHealthDetail: React.FC<CropHealthDetailProps> = ({ parcelId }) => {
  const { t } = useTranslation('crop-health');
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

        const a = aRes.status === 'fulfilled' ? aRes.value?.assessments?.[0] : null;
        if (a) setAssessment(a);

        if (tRes.status === 'fulfilled' && tRes.value?.points) {
          setTrend(tRes.value.points);
        }
        if (cRes.status === 'fulfilled' && cRes.value?.pairs) {
          setCorrelation(cRes.value.pairs);
        }

        const species = a?.species;
        if (species) {
          try {
            const pResp = await fetch(
              `/api/bioorchestrator/api/graph/phenology-params?species=${encodeURIComponent(species)}`
            );
            if (pResp.ok) setPhenology(await pResp.json());
          } catch { /* optional */ }
        }
      } catch { /* handle gracefully */ }
      finally { setLoading(false); }
    };

    fetchData();
  }, [parcelId]);

  if (loading) {
    return <div className="text-nkz-text-muted text-sm p-4">{t('contextPanel.loading')}</div>;
  }

  if (!assessment) {
    return (
      <div className="text-center p-4">
        <span className="text-2xl">🌱</span>
        <p className="text-nkz-text-muted text-sm mt-1">{t('contextPanel.noData')}</p>
      </div>
    );
  }

  const sevStyle = SEVERITY_STYLES[assessment.overallSeverity as 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'] || SEVERITY_STYLES.LOW;
  const trendCW = trend.filter(p => p.cwsi != null).map(p => p.cwsi!);
  const trendMDS = trend.filter(p => p.mds != null).map(p => p.mds!);
  const trendDir = trendCW.length >= 2 ? (trendCW[trendCW.length - 1] - trendCW[0]) : null;

  return (
    <div>
      {/* CWSI Section */}
      {assessment.cwsiValue != null && (
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-nkz-text-secondary text-xs">{t('contextPanel.cwsiLabel')}</span>
            {trendCW.length >= 2 && <Sparkline data={trendCW} color="#dc2626" />}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-2 bg-nkz-border rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min(assessment.cwsiValue * 100, 100)}%`,
                  background: assessment.cwsiValue > 0.6 ? '#dc2626' : assessment.cwsiValue > 0.3 ? '#d97706' : '#16a34a',
                }}
              />
            </div>
            <span className="text-nkz-text-primary text-sm font-mono w-10 text-right">{assessment.cwsiValue.toFixed(2)}</span>
          </div>
          {trendDir != null && (
            <p className="text-xs mt-1" style={{ color: Number(trendDir) > 0 ? '#dc2626' : '#16a34a' }}>
              {Number(trendDir) > 0 ? '↑' : '↓'} {Math.abs(Number(trendDir)).toFixed(2)} 7d
              {Number(trendDir) > 0.05 ? ` — ${t('contextPanel.declining')}` : Number(trendDir) < -0.05 ? ` — ${t('contextPanel.improving')}` : ` — ${t('contextPanel.stable')}`}
            </p>
          )}
        </div>
      )}

      {/* MDS Section */}
      {assessment.mdsValue != null && (
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-nkz-text-secondary text-xs">{t('contextPanel.mdsLabel')}</span>
            {trendMDS.length >= 2 && <Sparkline data={trendMDS} color="#7c3aed" />}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-nkz-text-primary font-mono text-sm">{assessment.mdsValue.toFixed(0)}µm</span>
            {assessment.mdsSeverity && <SeverityBadge severity={assessment.mdsSeverity} />}
          </div>
        </div>
      )}

      {/* Water Balance Section */}
      {assessment.waterBalanceDeficit != null && (
        <div className="mb-3">
          <span className="text-nkz-text-secondary text-xs block mb-1">{t('contextPanel.waterBalanceLabel')}</span>
          <span
            className="font-mono text-sm"
            style={{ color: assessment.waterBalanceDeficit < 0 ? '#dc2626' : '#16a34a' }}
          >
            {assessment.waterBalanceDeficit > 0 ? '+' : ''}{assessment.waterBalanceDeficit.toFixed(1)}mm
          </span>
        </div>
      )}

      {/* Soil Properties Section */}
      {assessment.soilProperties?.hasData && (
        <div className="mb-3 bg-nkz-surface-raised rounded p-2">
          <span className="text-nkz-text-secondary text-xs block mb-1">🌱 {t('detail.soilProperties')}</span>
          <div className="grid grid-cols-3 gap-1 text-xs">
            <div className="text-nkz-text-muted">FC: <span className="text-nkz-text-primary">{assessment.soilProperties.fieldCapacity.toFixed(2)}</span></div>
            <div className="text-nkz-text-muted">WP: <span className="text-nkz-text-primary">{assessment.soilProperties.wiltingPoint.toFixed(2)}</span></div>
            <div className="text-nkz-text-muted">Ksat: <span className="text-nkz-text-primary">{assessment.soilProperties.ksatMmH.toFixed(0)} mm/h</span></div>
          </div>
          <p className="text-nkz-text-muted text-xs mt-1">
            {assessment.soilProperties.usdaTextureClass} · Grupo SCS {assessment.soilProperties.scsHydrologicGroup} · {assessment.soilProperties.source}
          </p>
          {assessment.soilWaterRatio != null && assessment.soilAWCmm != null && (
            <div className="mt-2">
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-nkz-text-muted text-xs">Reserva de agua</span>
                <span className="text-nkz-text-muted text-xs">{assessment.soilWaterMm?.toFixed(0)}/{assessment.soilAWCmm.toFixed(0)} mm</span>
              </div>
              <div className="h-2 bg-nkz-border rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${Math.min((assessment.soilWaterRatio || 0) * 100, 100)}%`,
                    background: (assessment.soilWaterRatio || 0) > 0.5 ? '#16a34a' : (assessment.soilWaterRatio || 0) > 0.3 ? '#d97706' : '#dc2626',
                  }}
                />
              </div>
            </div>
          )}
          {assessment.waterloggingRiskLevel && assessment.waterloggingRiskLevel !== 'LOW' && (
            <p className="text-xs mt-1" style={{ color: '#1e40af' }}>
              💦 Riesgo de encharcamiento: {assessment.waterloggingRiskLevel} ({assessment.waterloggingSaturationHours?.toFixed(0)}h)
            </p>
          )}
        </div>
      )}

      {/* Phenology Params */}
      {phenology && (
        <div className="mb-3 bg-nkz-surface-raised rounded p-2">
          <span className="text-nkz-text-secondary text-xs block mb-1">{t('contextPanel.phenologyParamsLabel')}</span>
          <div className="grid grid-cols-4 gap-1 text-center">
            <div><span className="text-nkz-text-muted text-xs">Kc</span><br /><strong className="text-nkz-text-primary text-xs">{phenology.kc?.toFixed(2)}</strong></div>
            <div><span className="text-nkz-text-muted text-xs">D1</span><br /><strong className="text-nkz-text-primary text-xs">{phenology.d1?.toFixed(1)}°C</strong></div>
            <div><span className="text-nkz-text-muted text-xs">D2</span><br /><strong className="text-nkz-text-primary text-xs">{phenology.d2?.toFixed(1)}°C</strong></div>
            <div><span className="text-nkz-text-muted text-xs">MDS ref</span><br /><strong className="text-nkz-text-primary text-xs">{phenology.mds_ref?.toFixed(0)}µm</strong></div>
          </div>
          {phenology.provenance && (
            <p className="text-nkz-text-muted text-xs mt-1">
              📚 {phenology.provenance.short}
              {phenology.provenance.author && ` — ${phenology.provenance.author}`}
              {phenology.provenance.year && ` (${phenology.provenance.year})`}
            </p>
          )}
          {phenology.match_level && (
            <p className="text-nkz-text-muted text-xs">{t('contextPanel.matchLevel', { level: phenology.match_level.toUpperCase() })}</p>
          )}
        </div>
      )}

      {/* Composite Stress */}
      {assessment.compositeStressIndex != null && (
        <div className="mb-3">
          <span className="text-nkz-text-secondary text-xs block mb-1">{t('contextPanel.compositeStressLabel')}</span>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-2 bg-nkz-border rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min(assessment.compositeStressIndex, 100)}%`,
                  background: assessment.compositeStressIndex > 75 ? '#dc2626' : assessment.compositeStressIndex > 50 ? '#d97706' : '#16a34a',
                }}
              />
            </div>
            <span className="text-nkz-text-primary text-sm font-mono">{assessment.compositeStressIndex.toFixed(0)}/100</span>
          </div>
          {assessment.dominantStressor && assessment.dominantStressor !== 'none' && (
            <p className="text-nkz-text-muted text-xs mt-1">{t('contextPanel.dominantStressor', { stressor: assessment.dominantStressor })}</p>
          )}
        </div>
      )}

      {/* WUE */}
      {assessment.wueStatus != null && (
        <div className="mb-3">
          <span className="text-nkz-text-secondary text-xs block mb-1">{t('contextPanel.wueLabel')}</span>
          {assessment.wueStatus === 'suppressed' ? (
            <p className="text-nkz-text-muted text-xs">⚠️ {t('contextPanel.wueSuppressed')}</p>
          ) : (
            <>
              {assessment.wueKgM3 != null && (
                <div className="flex items-center gap-2">
                  <span className="text-nkz-text-primary font-mono text-sm">{assessment.wueKgM3.toFixed(2)} kg/m³</span>
                  <span
                    className="text-xs px-1.5 py-0.5 rounded"
                    style={{
                      background: assessment.wueTrend === 'improving' ? '#dcfce7' : assessment.wueTrend === 'declining' ? '#fee2e2' : '#f3f4f6',
                      color: assessment.wueTrend === 'improving' ? '#166534' : assessment.wueTrend === 'declining' ? '#991b1b' : '#374151',
                    }}
                  >
                    {assessment.wueTrend === 'improving' ? '↑' : assessment.wueTrend === 'declining' ? '↓' : '→'}
                  </span>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Yield Gap */}
      {assessment.yieldUtilizationPct != null && (
        <div className="mb-3">
          <span className="text-nkz-text-secondary text-xs block mb-1">{t('contextPanel.yieldGapLabel')}</span>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-2 bg-nkz-border rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min(assessment.yieldUtilizationPct, 100)}%`,
                  background: assessment.yieldUtilizationPct > 80 ? '#16a34a' : assessment.yieldUtilizationPct > 60 ? '#d97706' : '#dc2626',
                }}
              />
            </div>
            <span className="text-nkz-text-primary text-sm font-mono">{assessment.yieldUtilizationPct.toFixed(0)}%</span>
          </div>
        </div>
      )}

      {/* Data Fidelity */}
      {assessment.dataFidelity && (
        <div className="mb-3">
          <span className="text-nkz-text-secondary text-xs block mb-1">{t('contextPanel.dataFidelityLabel')}</span>
          <span
            className="text-xs px-2 py-0.5 rounded"
            style={{
              background: assessment.dataFidelity === 'onsite_calibrated' ? '#dcfce7' : assessment.dataFidelity === 'onsite_uncalibrated' ? '#fef3c7' : '#e0e7ff',
              color: assessment.dataFidelity === 'onsite_calibrated' ? '#166534' : assessment.dataFidelity === 'onsite_uncalibrated' ? '#92400e' : '#3730a3',
            }}
          >
            {assessment.dataFidelity}
          </span>
        </div>
      )}

      {/* Correlation */}
      {correlation.length >= 3 && (
        <div className="mb-3">
          <span className="text-nkz-text-secondary text-xs block mb-1">{t('contextPanel.correlationLabel')}</span>
          <div className="space-y-0.5">
            {correlation.slice(-5).map((p, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="text-nkz-text-muted w-20">{p.date?.slice(0, 10)}</span>
                <span style={{ color: (p.ndvi || 0) > 0.5 ? '#16a34a' : '#d97706' }}>NDVI {(p.ndvi || 0).toFixed(2)}</span>
                <span style={{ color: (p.cwsi || 0) > 0.5 ? '#dc2626' : '#16a34a' }}>CWSI {(p.cwsi || 0).toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recommendation footer */}
      <div
        className="p-2 rounded border"
        style={{ background: sevStyle.bg, borderColor: sevStyle.border }}
      >
        <div className="flex items-start gap-2">
          <span className="text-sm">
            {assessment.overallSeverity === 'CRITICAL' ? '🔴' : assessment.overallSeverity === 'HIGH' ? '🟠' : assessment.overallSeverity === 'MEDIUM' ? '🟡' : '🟢'}
          </span>
          <div>
            <strong className="text-nkz-text-primary text-sm">
              {t(actionLabels[assessment.recommendedAction] || assessment.recommendedAction)}
            </strong>
            <p className="text-nkz-text-muted text-xs mt-0.5">
              {assessment.cwsiValue != null && assessment.cwsiValue > 0.6 && 'CWSI elevado. '}
              {assessment.mdsSeverity === 'CRITICAL' && 'Contracción del tronco crítica. '}
              {assessment.waterBalanceDeficit != null && assessment.waterBalanceDeficit < -5 && 'Déficit hídrico significativo. '}
              {t('contextPanel.basedOn', {
                source: assessment.phenologySource === 'bioorchestrator' ? t('contextPanel.specificParams') : t('contextPanel.genericParams')
              })}.
            </p>
          </div>
        </div>
      </div>

      {/* Footer */}
      <p className="text-nkz-text-muted text-xs mt-2">
        {t('contextPanel.updated')} {assessment.assessedAt ? new Date(assessment.assessedAt).toLocaleString() : '—'}
        {' · '}
        <a href={`/api/crop-health/assessments/export?parcelId=${parcelId}&days=30`} className="text-nkz-accent-base underline" download>
          📥 {t('contextPanel.exportCsv')}
        </a>
      </p>
    </div>
  );
};

export default CropHealthDetail;
