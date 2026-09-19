import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Sparkline } from './shared/Sparkline';
import { SeverityBadge, SEVERITY_STYLES } from './shared/SeverityBadge';
import { Badge, MetricSection, ProgressBar } from './detail/MetricPrimitives';
import type {
  AssessmentData,
  CorrelationPoint,
  CorrelationStats,
  PhenologyParams,
  TrendPoint,
} from '../types/assessment';

type DetailTab = 'water' | 'plant' | 'yield' | 'analytics';

interface CropHealthDetailTabsProps {
  parcelId: string;
  assessment: AssessmentData | null;
  phenology: PhenologyParams | null;
  trend: TrendPoint[];
  correlation: CorrelationPoint[];
  correlationStats: CorrelationStats | null;
}

const actionLabels: Record<string, string> = {
  NO_ACTION: 'contextPanel.noAction',
  MONITOR: 'contextPanel.monitorEvolution',
  IRRIGATE_SCHEDULED: 'contextPanel.scheduleIrrigation',
  IRRIGATE_IMMEDIATE: 'contextPanel.irrigateImmediately',
};

const TAB_KEYS: DetailTab[] = ['water', 'plant', 'yield', 'analytics'];

const CropHealthDetailTabs: React.FC<CropHealthDetailTabsProps> = ({
  parcelId,
  assessment,
  phenology,
  trend,
  correlation,
  correlationStats,
}) => {
  const { t } = useTranslation('crop-health');
  const [activeTab, setActiveTab] = useState<DetailTab>('water');

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
    <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg overflow-hidden mb-3">
      <div className="flex border-b border-nkz-border bg-nkz-surface">
        {TAB_KEYS.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`flex-1 px-2 py-2 text-xs font-medium border-none cursor-pointer ${
              activeTab === tab
                ? 'bg-nkz-accent-soft text-nkz-accent-strong border-b-2 border-b-nkz-accent-base'
                : 'bg-transparent text-nkz-text-muted hover:text-nkz-text-primary'
            }`}
          >
            {t(`tabs.${tab}`)}
          </button>
        ))}
      </div>

      <div className="p-2 space-y-2">
      {activeTab === 'water' && (
        <>
      {/* CWSI Section */}
      {assessment.cwsiValue != null && (
        <MetricSection>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">
              {t('contextPanel.cwsiLabel')}
            </span>
            {trendCW.length >= 2 && <Sparkline data={trendCW} color="var(--nkz-color-danger)" />}
          </div>
          <ProgressBar value={assessment.cwsiValue * 100} intent={assessment.cwsiValue > 0.6 ? 'negative' : assessment.cwsiValue > 0.3 ? 'warning' : 'positive'} />
          {trendDir != null && (
            <p className="text-xs mt-1" style={{ color: Number(trendDir) > 0 ? 'var(--nkz-color-danger)' : 'var(--nkz-color-success)' }}>
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
            {trendMDS.length >= 2 && <Sparkline data={trendMDS} color="var(--nkz-color-info)" />}
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
          <span className="font-mono text-sm" style={{ color: assessment.waterBalanceDeficit < 0 ? 'var(--nkz-color-danger)' : 'var(--nkz-color-success)' }}>
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
            <p className="text-xs mt-1" style={{ color: 'var(--nkz-color-info)' }}>
              💦 {assessment.waterloggingRisk?.riskLevel ?? assessment.waterloggingRiskLevel}
              {' '}({(assessment.waterloggingRisk?.saturationHours ?? assessment.waterloggingSaturationHours)?.toFixed(0)}h)
              {assessment.waterloggingRisk?.excessMm != null && ` · +${assessment.waterloggingRisk.excessMm.toFixed(0)} mm`}
              {assessment.waterloggingRisk?.drainageRateMmH != null && ` · drain ${assessment.waterloggingRisk.drainageRateMmH.toFixed(1)} mm/h`}
            </p>
          )}
        </MetricSection>
      )}
        </>
      )}

      {activeTab === 'plant' && (
        <>
      {/* Soil suitability — committed crop × real parcel soil (bioorch verdict) */}
      {assessment.soilSuitability && (
        <MetricSection>
          <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider block mb-1">
            {t('soilSuitability.title')}
          </span>
          <div className="flex items-center gap-2 text-sm">
            <Badge intent={
              assessment.soilSuitability.verdict === 'suitable' ? 'positive'
                : assessment.soilSuitability.verdict === 'marginal' ? 'warning'
                  : assessment.soilSuitability.verdict === 'unsuitable' ? 'negative'
                    : 'default'
            }>
              {t(`soilSuitability.verdict.${assessment.soilSuitability.verdict}`)}
            </Badge>
            {assessment.soilSuitability.confidence && (
              <span className="text-nkz-text-muted">
                {t(`soilSuitability.confidence.${assessment.soilSuitability.confidence}`)}
              </span>
            )}
          </div>
          {assessment.soilSuitability.verdict === 'unknown' ? (
            <p className="text-xs text-nkz-text-muted mt-1">{t('soilSuitability.noData')}</p>
          ) : (
            assessment.soilSuitability.reason && (
              <p className="text-xs text-nkz-text-primary mt-1">{assessment.soilSuitability.reason}</p>
            )
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
            {assessment.sar.isFlooded ? t('detail.sarFlooded') : t('detail.sarNoFlood')}
            {assessment.sar.surfaceMoistureIndex != null && ` · SMI ${assessment.sar.surfaceMoistureIndex.toFixed(2)}`}
            {assessment.sar.waterloggingRisk && ` · ${assessment.sar.waterloggingRisk}`}
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
        </>
      )}

      {activeTab === 'yield' && (
        <>
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
              {assessment.baselineYieldKgHa != null && ` · ${t('detail.baselineYield', { value: assessment.baselineYieldKgHa.toFixed(0) })}`}
              {assessment.predictedYieldKgHa != null && ` · ${t('detail.predictedYield', { value: assessment.predictedYieldKgHa.toFixed(0) })}`}
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

      {/* Recommendation */}
      <div className="bg-nkz-surface border border-nkz-border rounded-lg p-3" style={{ borderLeft: `4px solid ${sevStyle.border}` }}>
        <div className="flex items-start gap-2">
          <SeverityBadge severity={assessment.overallSeverity} dotOnly />
          <div>
            <strong className="text-sm text-nkz-text-primary">
              {t(actionLabels[assessment.recommendedAction] || assessment.recommendedAction)}
            </strong>
            <p className="text-xs text-nkz-text-muted mt-0.5">
              {assessment.cwsiValue != null && assessment.cwsiValue > 0.6 && `${t('detail.hints.cwsiHigh')} `}
              {assessment.mdsSeverity === 'CRITICAL' && `${t('detail.hints.mdsCritical')} `}
              {assessment.waterBalanceDeficit != null && assessment.waterBalanceDeficit < -5 && `${t('detail.hints.deficit')} `}
              {t('contextPanel.basedOn', {
                source: assessment.phenologySource === 'bioorchestrator' ? t('contextPanel.specificParams') : t('contextPanel.genericParams'),
              })}.
            </p>
          </div>
        </div>
      </div>
        </>
      )}

      {activeTab === 'analytics' && (
        <>
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
                <span style={{ color: (p.ndvi || 0) > 0.5 ? 'var(--nkz-color-success)' : 'var(--nkz-color-warning)' }}>NDVI {(p.ndvi || 0).toFixed(2)}</span>
                <span style={{ color: (p.cwsi || 0) > 0.5 ? 'var(--nkz-color-danger)' : 'var(--nkz-color-success)' }}>CWSI {(p.cwsi || 0).toFixed(2)}</span>
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

      <p className="text-xs text-nkz-text-muted">
        {t('contextPanel.updated')} {assessment.assessedAt ? new Date(assessment.assessedAt).toLocaleString() : '—'}
        {' · '}
        <a href={`/api/crop-health/assessments/export?parcelId=${parcelId}&days=30`} className="text-nkz-accent-base underline" download>
          📥 {t('contextPanel.exportCsv')}
        </a>
      </p>
        </>
      )}
      </div>
    </div>
  );
};

export default CropHealthDetailTabs;
