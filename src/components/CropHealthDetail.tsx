import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { cropHealthFetch, PHENOLOGY_PARAMS_URL } from '../api/cropHealthApi';
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

interface CorrelationStats {
  n: number;
  r2: number | null;
  slope: number | null;
  intercept: number | null;
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
  compositeStress?: {
    index?: number;
    dominantStressor?: string;
    waterContribution?: number;
    thermalContribution?: number;
    vigorContribution?: number;
    stageKy?: number;
  };
  yieldUtilizationPct?: number;
  yieldGapConfidence?: string;
  predictedYieldKgHa?: number;
  baselineYieldKgHa?: number;
  thermalCondition?: string;
  thermalSeverity?: string;
  heatStressHours?: number;
  frostHours?: number;
  thermalDataFidelity?: string;
  vigorIndex?: number;
  vigorCondition?: string;
  growthAnomaly?: number;
  vigorIndexUsed?: string;
  vigorDataFidelity?: string;
  dataFidelity?: string;
  wueStatus?: string;
  wueKgM3?: number;
  wueBiomassKg?: number;
  wueWaterAppliedMm?: number;
  wueTrend?: string;
  species?: string;
  cropSpecies?: string;
  phenologyDeviation?: string;
  stageProgressPct?: number;
  gddAccumulated?: number;
  vhi?: { vhi?: number; vci?: number; tci?: number; asiPct?: number; tciSource?: string };
  sar?: { isFlooded?: boolean; floodStage?: string; surfaceMoistureIndex?: number; waterloggingRisk?: string; dataFidelity?: string };
  compactionRisk?: {
    level?: string;
    score?: number;
    susceptibilityScore?: number;
    factors?: string[];
    moistureWarning?: boolean;
    vigorConcern?: boolean;
    requiresVerification?: boolean;
    advisory?: string;
  };
  soilSensors?: { ph?: number; ec?: number; moisturePct?: number; temperatureC?: number };
  soilProperties?: {
    sandPct?: number;
    clayPct?: number;
    fieldCapacity: number;
    wiltingPoint: number;
    ksatMmH: number;
    scsHydrologicGroup: string;
    usdaTextureClass: string;
    source: string;
    hasData: boolean;
  };
  soilWaterMm?: number;
  soilAWCmm?: number;
  soilWaterRatio?: number;
  soilWaterBalance?: {
    swMm?: number;
    awcMm?: number;
    swRatio?: number;
    stressCoefficientKs?: number;
    actualETmm?: number;
    deepPercolationMm?: number;
    depletionFractionP?: number;
  };
  waterloggingRiskLevel?: string;
  waterloggingSaturationHours?: number;
  waterloggingRisk?: {
    riskLevel?: string;
    saturationHours?: number;
    excessMm?: number;
    drainageRateMmH?: number;
  };
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

/** Inline progress bar with intent-based color */
function ProgressBar({ value, intent }: { value: number; intent?: 'positive' | 'warning' | 'negative' | 'default' }) {
  const barCls = intent === 'negative' ? 'bg-red-500' : intent === 'warning' ? 'bg-amber-500' : intent === 'positive' ? 'bg-green-500' : 'bg-nkz-accent-base';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${barCls}`} style={{ width: `${Math.min(value, 100)}%` }} />
      </div>
      <span className="text-sm font-mono text-nkz-text-primary">{Math.round(value)}%</span>
    </div>
  );
}

/** Inline badge using NKZ intent styles */
function Badge({ intent, children }: { intent?: 'positive' | 'warning' | 'negative' | 'info' | 'default'; children: React.ReactNode }) {
  const cls: Record<string, string> = {
    positive: 'bg-green-100 text-green-800 border border-green-200',
    warning: 'bg-amber-100 text-amber-800 border border-amber-200',
    negative: 'bg-red-100 text-red-800 border border-red-200',
    info: 'bg-blue-100 text-blue-800 border border-blue-200',
    default: 'bg-gray-100 text-gray-800 border border-gray-200',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium leading-4 ${cls[intent || 'default']}`}>
      {children}
    </span>
  );
}

/** Section card */
function MetricSection({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 shadow-sm ${className}`}>
      {children}
    </div>
  );
}

const CropHealthDetail: React.FC<CropHealthDetailProps> = ({ parcelId }) => {
  const { t } = useTranslation('crop-health');
  const [assessment, setAssessment] = useState<AssessmentData | null>(null);
  const [phenology, setPhenology] = useState<PhenologyData | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [correlation, setCorrelation] = useState<CorrelationData[]>([]);
  const [correlationStats, setCorrelationStats] = useState<CorrelationStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!parcelId) return;
    setLoading(true);

    const fetchData = async () => {
      try {
        const [a, tRes, cRes] = await Promise.all([
          cropHealthFetch<{ assessments: AssessmentData[] }>(`/assessments/latest?parcelId=${parcelId}`),
          cropHealthFetch<{ points: TrendPoint[] }>(`/assessments/history?parcelId=${parcelId}&days=7`),
          cropHealthFetch<{ pairs: CorrelationData[]; stats?: CorrelationStats }>(`/assessments/correlation?parcelId=${parcelId}&days=30`),
        ]);

        const assessment = a?.assessments?.[0];
        if (assessment) setAssessment(assessment);
        if (tRes?.points) setTrend(tRes.points);
        if (cRes?.pairs) setCorrelation(cRes.pairs);
        if (cRes?.stats) setCorrelationStats(cRes.stats);

        const species = assessment?.species ?? assessment?.cropSpecies;
        if (species) {
          try {
            const pResp = await fetch(
              `${PHENOLOGY_PARAMS_URL}?species=${encodeURIComponent(species)}`,
              { credentials: 'include' },
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
    return (
      <div className="space-y-3 animate-pulse">
        {[1, 2, 3].map(i => (
          <div key={i} className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3">
            <div className="h-4 bg-gray-200 rounded w-2/3 mb-2" />
            <div className="h-3 bg-gray-200 rounded w-full" />
          </div>
        ))}
      </div>
    );
  }

  if (!assessment) {
    return (
      <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-4 text-center">
        <span className="text-2xl">🌱</span>
        <p className="text-sm text-nkz-text-muted mt-1">{t('contextPanel.noData')}</p>
        <p className="text-xs text-nkz-text-muted mt-1">{t('contextPanel.noDataHint')}</p>
      </div>
    );
  }

  const sevStyle = SEVERITY_STYLES[assessment.overallSeverity as 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'] || SEVERITY_STYLES.LOW;
  const trendCW = trend.filter(p => p.cwsi != null).map(p => p.cwsi!);
  const trendMDS = trend.filter(p => p.mds != null).map(p => p.mds!);
  const trendDir = trendCW.length >= 2 ? (trendCW[trendCW.length - 1] - trendCW[0]) : null;

  return (
    <div className="space-y-2">
      {/* CWSI Section */}
      {assessment.cwsiValue != null && (
        <MetricSection>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">
              {t('contextPanel.cwsiLabel')}
            </span>
            {trendCW.length >= 2 && <Sparkline data={trendCW} color="#dc2626" />}
          </div>
          <ProgressBar value={assessment.cwsiValue * 100} intent={assessment.cwsiValue > 0.6 ? 'negative' : assessment.cwsiValue > 0.3 ? 'warning' : 'positive'} />
          {trendDir != null && (
            <p className="text-xs mt-1" style={{ color: Number(trendDir) > 0 ? '#dc2626' : '#16a34a' }}>
              {Number(trendDir) > 0 ? '↑' : '↓'} {Math.abs(Number(trendDir)).toFixed(2)} 7d
              {' — '}
              {Number(trendDir) > 0.05 ? t('contextPanel.declining') : Number(trendDir) < -0.05 ? t('contextPanel.improving') : t('contextPanel.stable')}
            </p>
          )}
        </MetricSection>
      )}

      {/* MDS Section */}
      {assessment.mdsValue != null && (
        <MetricSection>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">
              {t('contextPanel.mdsLabel')}
            </span>
            {trendMDS.length >= 2 && <Sparkline data={trendMDS} color="#7c3aed" />}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-mono text-nkz-text-primary">{assessment.mdsValue.toFixed(0)}µm</span>
            {assessment.mdsSeverity && <SeverityBadge severity={assessment.mdsSeverity} />}
          </div>
        </MetricSection>
      )}

      {/* Water Balance Section */}
      {assessment.waterBalanceDeficit != null && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('contextPanel.waterBalanceLabel')}
          </span>
          <span className="font-mono text-sm" style={{ color: assessment.waterBalanceDeficit < 0 ? '#dc2626' : '#16a34a' }}>
            {assessment.waterBalanceDeficit > 0 ? '+' : ''}{assessment.waterBalanceDeficit.toFixed(1)}mm
          </span>
        </MetricSection>
      )}

      {/* Soil Properties */}
      {assessment.soilProperties?.hasData && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            🌱 {t('detail.soilProperties')}
          </span>
          <div className="grid grid-cols-3 gap-1 text-xs">
            <div className="text-nkz-text-muted">FC: <span className="text-nkz-text-primary font-medium">{assessment.soilProperties.fieldCapacity.toFixed(2)}</span></div>
            <div className="text-nkz-text-muted">WP: <span className="text-nkz-text-primary font-medium">{assessment.soilProperties.wiltingPoint.toFixed(2)}</span></div>
            <div className="text-nkz-text-muted">Ksat: <span className="text-nkz-text-primary font-medium">{assessment.soilProperties.ksatMmH.toFixed(0)} mm/h</span></div>
          </div>
          <p className="text-xs text-nkz-text-muted mt-1">
            {assessment.soilProperties.usdaTextureClass} · SCS {assessment.soilProperties.scsHydrologicGroup} · {assessment.soilProperties.source}
            {assessment.soilProperties.sandPct != null && ` · Sand ${assessment.soilProperties.sandPct.toFixed(0)}%`}
            {assessment.soilProperties.clayPct != null && ` · Clay ${assessment.soilProperties.clayPct.toFixed(0)}%`}
          </p>
          {(assessment.soilWaterBalance || assessment.soilWaterRatio != null) && (
            <div className="mt-2">
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-xs text-nkz-text-muted">{t('detail.soilReservoir')}</span>
                <span className="text-xs text-nkz-text-muted">
                  {(assessment.soilWaterBalance?.swMm ?? assessment.soilWaterMm)?.toFixed(0)}/
                  {(assessment.soilWaterBalance?.awcMm ?? assessment.soilAWCmm)?.toFixed(0)} mm
                </span>
              </div>
              <ProgressBar
                value={((assessment.soilWaterBalance?.swRatio ?? assessment.soilWaterRatio) || 0) * 100}
                intent={((assessment.soilWaterBalance?.swRatio ?? assessment.soilWaterRatio) || 0) > 0.5 ? 'positive' : ((assessment.soilWaterBalance?.swRatio ?? assessment.soilWaterRatio) || 0) > 0.3 ? 'warning' : 'negative'}
              />
              {assessment.soilWaterBalance?.stressCoefficientKs != null && (
                <p className="text-xs text-nkz-text-muted mt-1">
                  Ks {assessment.soilWaterBalance.stressCoefficientKs.toFixed(2)}
                  {assessment.soilWaterBalance.actualETmm != null && ` · ETa ${assessment.soilWaterBalance.actualETmm.toFixed(1)} mm`}
                  {assessment.soilWaterBalance.deepPercolationMm != null && assessment.soilWaterBalance.deepPercolationMm > 0 && ` · DP ${assessment.soilWaterBalance.deepPercolationMm.toFixed(1)} mm`}
                </p>
              )}
            </div>
          )}
          {(assessment.waterloggingRisk?.riskLevel ?? assessment.waterloggingRiskLevel) &&
            (assessment.waterloggingRisk?.riskLevel ?? assessment.waterloggingRiskLevel) !== 'LOW' && (
            <p className="text-xs mt-1" style={{ color: '#1e40af' }}>
              💦 {assessment.waterloggingRisk?.riskLevel ?? assessment.waterloggingRiskLevel}
              {' '}({(assessment.waterloggingRisk?.saturationHours ?? assessment.waterloggingSaturationHours)?.toFixed(0)}h)
              {assessment.waterloggingRisk?.excessMm != null && ` · +${assessment.waterloggingRisk.excessMm.toFixed(0)} mm`}
              {assessment.waterloggingRisk?.drainageRateMmH != null && ` · drain ${assessment.waterloggingRisk.drainageRateMmH.toFixed(1)} mm/h`}
            </p>
          )}
        </MetricSection>
      )}

      {/* Phenology progress */}
      {(assessment.stageProgressPct != null || assessment.phenologyDeviation || assessment.gddAccumulated != null) && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('contextPanel.phenologyProgressLabel')}
          </span>
          {assessment.stageProgressPct != null && (
            <ProgressBar value={assessment.stageProgressPct} intent={assessment.stageProgressPct > 80 ? 'warning' : 'positive'} />
          )}
          <p className="text-xs text-nkz-text-muted mt-1">
            {assessment.phenologyDeviation && `${t('detail.phenologyDeviation')}: ${assessment.phenologyDeviation} · `}
            {assessment.gddAccumulated != null && `GDD ${assessment.gddAccumulated.toFixed(0)}`}
          </p>
        </MetricSection>
      )}

      {/* Thermal detail */}
      {(assessment.thermalCondition || assessment.heatStressHours != null) && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('thermal')}
          </span>
          <div className="flex items-center gap-2 text-sm">
            {assessment.thermalSeverity && <SeverityBadge severity={assessment.thermalSeverity} />}
            <span className="text-nkz-text-primary">{assessment.thermalCondition}</span>
          </div>
          {(assessment.heatStressHours != null || assessment.frostHours != null) && (
            <p className="text-xs text-nkz-text-muted mt-1">
              {assessment.heatStressHours != null && `Heat ${assessment.heatStressHours.toFixed(0)}h`}
              {assessment.frostHours != null && ` · Frost ${assessment.frostHours.toFixed(0)}h`}
              {assessment.thermalDataFidelity && ` · ${assessment.thermalDataFidelity}`}
            </p>
          )}
        </MetricSection>
      )}

      {/* Vigor detail */}
      {assessment.vigorIndex != null && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('vigor')}
          </span>
          <div className="flex items-center gap-2">
            <span className="text-sm font-mono text-nkz-text-primary">{assessment.vigorIndex.toFixed(2)}</span>
            {assessment.vigorCondition && <Badge>{assessment.vigorCondition}</Badge>}
          </div>
          <p className="text-xs text-nkz-text-muted mt-1">
            {assessment.vigorIndexUsed && `${assessment.vigorIndexUsed}`}
            {assessment.growthAnomaly != null && ` · anomaly ${assessment.growthAnomaly.toFixed(2)}`}
            {assessment.vigorDataFidelity && ` · ${assessment.vigorDataFidelity}`}
          </p>
        </MetricSection>
      )}

      {/* VHI / ASIS */}
      {assessment.vhi?.vhi != null && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('detail.vhiLabel')}
          </span>
          <div className="grid grid-cols-4 gap-1 text-xs text-center">
            <div><span className="text-nkz-text-muted">VHI</span><br /><strong>{assessment.vhi.vhi?.toFixed(0)}</strong></div>
            <div><span className="text-nkz-text-muted">VCI</span><br /><strong>{assessment.vhi.vci?.toFixed(0) ?? '—'}</strong></div>
            <div><span className="text-nkz-text-muted">TCI</span><br /><strong>{assessment.vhi.tci?.toFixed(0) ?? '—'}</strong></div>
            <div><span className="text-nkz-text-muted">ASIS</span><br /><strong>{assessment.vhi.asiPct?.toFixed(0) ?? '—'}%</strong></div>
          </div>
        </MetricSection>
      )}

      {/* SAR */}
      {assessment.sar && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('detail.sarLabel')}
          </span>
          <p className="text-xs text-nkz-text-primary">
            {assessment.sar.isFlooded ? '🌊 Flooded' : '✓ No flood'}
            {assessment.sar.surfaceMoistureIndex != null && ` · SMI ${assessment.sar.surfaceMoistureIndex.toFixed(2)}`}
            {assessment.sar.waterloggingRisk && ` · ${assessment.sar.waterloggingRisk}`}
          </p>
        </MetricSection>
      )}

      {/* Compaction */}
      {assessment.compactionRisk?.level && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('compaction.title')}
          </span>
          <ProgressBar value={assessment.compactionRisk.score ?? 0} intent={(assessment.compactionRisk.score ?? 0) > 60 ? 'negative' : 'warning'} />
          <p className="text-xs text-nkz-text-muted mt-1">
            {t(`compaction.level.${assessment.compactionRisk.level}`)}
            {assessment.compactionRisk.advisory && ` · ${t(`compaction.advisory.${assessment.compactionRisk.advisory}`)}`}
          </p>
        </MetricSection>
      )}

      {/* Soil sensors */}
      {assessment.soilSensors && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('detail.soilSensors')}
          </span>
          <div className="grid grid-cols-2 gap-1 text-xs">
            {assessment.soilSensors.ph != null && <div>pH <strong>{assessment.soilSensors.ph.toFixed(1)}</strong></div>}
            {assessment.soilSensors.ec != null && <div>EC <strong>{assessment.soilSensors.ec.toFixed(2)}</strong></div>}
            {assessment.soilSensors.moisturePct != null && <div>θ <strong>{assessment.soilSensors.moisturePct.toFixed(1)}%</strong></div>}
            {assessment.soilSensors.temperatureC != null && <div>T <strong>{assessment.soilSensors.temperatureC.toFixed(1)}°C</strong></div>}
          </div>
        </MetricSection>
      )}

      {/* Phenology Params */}
      {phenology && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('contextPanel.phenologyParamsLabel')}
          </span>
          <div className="grid grid-cols-4 gap-1 text-center text-xs">
            <div><span className="text-nkz-text-muted">Kc</span><br /><strong className="text-nkz-text-primary">{phenology.kc?.toFixed(2)}</strong></div>
            <div><span className="text-nkz-text-muted">D1</span><br /><strong className="text-nkz-text-primary">{phenology.d1?.toFixed(1)}°C</strong></div>
            <div><span className="text-nkz-text-muted">D2</span><br /><strong className="text-nkz-text-primary">{phenology.d2?.toFixed(1)}°C</strong></div>
            <div><span className="text-nkz-text-muted">MDS ref</span><br /><strong className="text-nkz-text-primary">{phenology.mds_ref?.toFixed(0)}µm</strong></div>
          </div>
          {phenology.provenance && (
            <p className="text-xs text-nkz-text-muted mt-1">
              📚 {phenology.provenance.short}{phenology.provenance.author && ` — ${phenology.provenance.author}`}{phenology.provenance.year && ` (${phenology.provenance.year})`}
            </p>
          )}
          {phenology.match_level && (
            <p className="text-xs text-nkz-text-muted">{t('contextPanel.matchLevel', { level: phenology.match_level.toUpperCase() })}</p>
          )}
        </MetricSection>
      )}

      {/* Composite Stress */}
      {assessment.compositeStressIndex != null && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('contextPanel.compositeStressLabel')}
          </span>
          <ProgressBar value={Math.min(assessment.compositeStressIndex, 100)} intent={assessment.compositeStressIndex > 75 ? 'negative' : assessment.compositeStressIndex > 50 ? 'warning' : 'positive'} />
          {assessment.dominantStressor && assessment.dominantStressor !== 'none' && (
            <p className="text-xs text-nkz-text-muted mt-1">{t('contextPanel.dominantStressor', { stressor: assessment.dominantStressor })}</p>
          )}
          {assessment.compositeStress && (
            <div className="grid grid-cols-3 gap-1 text-xs mt-2">
              {assessment.compositeStress.waterContribution != null && (
                <div className="text-nkz-text-muted">💧 {assessment.compositeStress.waterContribution.toFixed(0)}</div>
              )}
              {assessment.compositeStress.thermalContribution != null && (
                <div className="text-nkz-text-muted">🔥 {assessment.compositeStress.thermalContribution.toFixed(0)}</div>
              )}
              {assessment.compositeStress.vigorContribution != null && (
                <div className="text-nkz-text-muted">🌿 {assessment.compositeStress.vigorContribution.toFixed(0)}</div>
              )}
            </div>
          )}
          {assessment.compositeStress?.stageKy != null && (
            <p className="text-xs text-nkz-text-muted mt-1">Ky {assessment.compositeStress.stageKy.toFixed(2)}</p>
          )}
        </MetricSection>
      )}

      {/* WUE */}
      {assessment.wueStatus != null && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('contextPanel.wueLabel')}
          </span>
          {assessment.wueStatus === 'suppressed' ? (
            <p className="text-xs text-nkz-text-muted">⚠️ {t('contextPanel.wueSuppressed')}</p>
          ) : (
            assessment.wueKgM3 != null && (
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-mono text-nkz-text-primary">{assessment.wueKgM3.toFixed(2)} kg/m³</span>
                  <Badge intent={assessment.wueTrend === 'improving' ? 'positive' : assessment.wueTrend === 'declining' ? 'negative' : 'default'}>
                    {assessment.wueTrend === 'improving' ? '↑' : assessment.wueTrend === 'declining' ? '↓' : '→'}
                  </Badge>
                </div>
                {(assessment.wueBiomassKg != null || assessment.wueWaterAppliedMm != null) && (
                  <p className="text-xs text-nkz-text-muted mt-1">
                    {assessment.wueBiomassKg != null && `${assessment.wueBiomassKg.toFixed(0)} kg biomass`}
                    {assessment.wueWaterAppliedMm != null && ` · ${assessment.wueWaterAppliedMm.toFixed(0)} mm applied`}
                  </p>
                )}
              </div>
            )
          )}
        </MetricSection>
      )}

      {/* Yield Gap */}
      {assessment.yieldUtilizationPct != null && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('contextPanel.yieldGapLabel')}
          </span>
          <ProgressBar value={Math.min(assessment.yieldUtilizationPct, 100)} intent={assessment.yieldUtilizationPct > 80 ? 'positive' : assessment.yieldUtilizationPct > 60 ? 'warning' : 'negative'} />
          {assessment.yieldGapConfidence && (
            <p className="text-xs text-nkz-text-muted mt-1">
              {t('contextPanel.yieldGapConfidence', { confidence: assessment.yieldGapConfidence })}
              {assessment.baselineYieldKgHa != null && ` · baseline ${assessment.baselineYieldKgHa.toFixed(0)} kg/ha`}
            </p>
          )}
        </MetricSection>
      )}

      {/* Data Fidelity */}
      {assessment.dataFidelity && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('contextPanel.dataFidelityLabel')}
          </span>
          <Badge intent={assessment.dataFidelity === 'onsite_calibrated' ? 'positive' : assessment.dataFidelity === 'onsite_uncalibrated' ? 'warning' : 'info'}>
            {assessment.dataFidelity}
          </Badge>
        </MetricSection>
      )}

      {/* Correlation */}
      {correlation.length >= 3 && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('contextPanel.correlationLabel')}
          </span>
          <div className="space-y-0.5">
            {correlation.slice(-5).map((p, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="text-nkz-text-muted w-20">{p.date?.slice(0, 10)}</span>
                <span style={{ color: (p.ndvi || 0) > 0.5 ? '#16a34a' : '#d97706' }}>NDVI {(p.ndvi || 0).toFixed(2)}</span>
                <span style={{ color: (p.cwsi || 0) > 0.5 ? '#dc2626' : '#16a34a' }}>CWSI {(p.cwsi || 0).toFixed(2)}</span>
              </div>
            ))}
          </div>
          {correlationStats?.r2 != null && correlationStats.n >= 3 && (
            <p className="text-xs text-nkz-text-muted mt-1">
              {t('detail.correlationStats', { r2: correlationStats.r2.toFixed(3), n: correlationStats.n })}
            </p>
          )}
        </MetricSection>
      )}

      {/* Recommendation */}
      <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 shadow-sm" style={{ borderLeft: `4px solid ${sevStyle.border}` }}>
        <div className="flex items-start gap-2">
          <span className="text-base">
            {assessment.overallSeverity === 'CRITICAL' ? '🔴' : assessment.overallSeverity === 'HIGH' ? '🟠' : assessment.overallSeverity === 'MEDIUM' ? '🟡' : '🟢'}
          </span>
          <div>
            <strong className="text-sm text-nkz-text-primary">
              {t(actionLabels[assessment.recommendedAction] || assessment.recommendedAction)}
            </strong>
            <p className="text-xs text-nkz-text-muted mt-0.5">
              {assessment.cwsiValue != null && assessment.cwsiValue > 0.6 && 'CWSI elevado. '}
              {assessment.mdsSeverity === 'CRITICAL' && 'Contracción crítica. '}
              {assessment.waterBalanceDeficit != null && assessment.waterBalanceDeficit < -5 && 'Déficit significativo. '}
              {t('contextPanel.basedOn', {
                source: assessment.phenologySource === 'bioorchestrator' ? t('contextPanel.specificParams') : t('contextPanel.genericParams')
              })}.
            </p>
          </div>
        </div>
      </div>

      {/* Footer */}
      <p className="text-xs text-nkz-text-muted">
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
