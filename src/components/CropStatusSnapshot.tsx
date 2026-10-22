import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { authHeaders, CROP_CONTEXT_URL, cropHealthFetch } from '../api/cropHealthApi';
import { SeverityBadge } from './shared/SeverityBadge';

interface CropContext {
  crop?: { eppo?: string; name?: string; scientific_name?: string };
  variety?: { name?: string };
  management?: string;
  season?: { gdd_accumulated?: number };
  phenology?: {
    stage?: string;
    stage_gdd_min?: number;
    stage_gdd_max?: number;
    ky?: number;
  };
}

interface Assessment {
  cwsiValue?: number;
  mdsValue?: number;
  mdsSeverity?: string;
  waterBalanceDeficit?: number;
  overallSeverity: string;
  recommendedAction: string;
  assessedAt?: string;
  thermalCondition?: string;
  thermalSeverity?: string;
  vigorIndex?: number;
  vigorCondition?: string;
  compositeStressIndex?: number;
  dominantStressor?: string;
  dataFidelity?: string;
  phenologySource?: string;
  cropSpecies?: string;
  cropName?: string;
  varietyName?: string;
  phenologyStage?: string;
  gddAccumulated?: number;
  kc?: number;
  management?: string;
  soilProperties?: {
    sandPct: number;
    fieldCapacity: number;
    wiltingPoint: number;
    ksatMmH: number;
    scsHydrologicGroup: string;
    usdaTextureClass: string;
    source: string;
    hasData: boolean;
  };
  soilWaterBalance?: {
    swMm: number;
    awcMm: number;
    swRatio: number;
    stressLevel: string;
    soilMoistureConfidence: string;
  };
  waterloggingRisk?: {
    riskLevel: string;
    saturationHours: number;
  };
}

interface CropStatusSnapshotProps {
  parcelId: string;
  parcelName?: string;
}

function cwsiPhrase(cwsi: number): string {
  if (cwsi < 0.2) return 'summary.cwsi.none';
  if (cwsi < 0.4) return 'summary.cwsi.mild';
  if (cwsi < 0.6) return 'summary.cwsi.moderate';
  if (cwsi < 0.8) return 'summary.cwsi.high';
  return 'summary.cwsi.severe';
}

function gddProgress(
  gdd: number | undefined,
  stageMin: number | undefined,
  stageMax: number | undefined,
): number | null {
  if (gdd == null || stageMin == null || stageMax == null) return null;
  if (stageMax <= stageMin) return null;
  return Math.min(100, Math.max(0, ((gdd - stageMin) / (stageMax - stageMin)) * 100));
}

const actionLabelKey = (action: string): string => {
  switch (action) {
    case 'NO_ACTION': return 'action.noAction';
    case 'MONITOR': return 'action.monitor';
    case 'IRRIGATE_SCHEDULED': return 'action.irrigateScheduled';
    case 'IRRIGATE_IMMEDIATE': return 'action.irrigateImmediate';
    default: return action;
  }
};

function FidelityBadge({ fidelity }: { fidelity: string }) {
  const key = fidelity.replace(/^(onsite_|regional_)/, '').replace(/_proxy$/, '');
  const cls: Record<string, string> = {
    calibrated: 'bg-nkz-success-soft text-nkz-success-strong border border-nkz-success',
    onsite: 'bg-nkz-warning-soft text-nkz-warning-strong border border-nkz-warning',
    uncalibrated: 'bg-nkz-warning-soft text-nkz-warning-strong border border-nkz-warning',
    local: 'bg-nkz-surface-sunken text-nkz-text-secondary border border-nkz-border',
    regional: 'bg-nkz-info-soft text-nkz-info-strong border border-nkz-info',
    modeled: 'bg-nkz-info-soft text-nkz-info-strong border border-nkz-info',
    proxy: 'bg-nkz-info-soft text-nkz-info-strong border border-nkz-info',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium leading-4 ${cls[key] || 'bg-nkz-surface-sunken text-nkz-text-secondary border border-nkz-border'}`}>
      {fidelity}
    </span>
  );
}

function MetricChip({ icon, text, intent }: { icon: string; text: string; intent?: 'positive' | 'warning' | 'negative' | 'default' }) {
  const cls = intent === 'negative'
    ? 'bg-nkz-danger-soft text-nkz-danger-strong border border-nkz-danger'
    : intent === 'warning'
    ? 'bg-nkz-warning-soft text-nkz-warning-strong border border-nkz-warning'
    : intent === 'positive'
    ? 'bg-nkz-success-soft text-nkz-success-strong border border-nkz-success'
    : 'bg-nkz-surface-sunken text-nkz-text-secondary border border-nkz-border';
  return <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>{icon} {text}</span>;
}

const CropStatusSnapshot: React.FC<CropStatusSnapshotProps> = ({ parcelId, parcelName }) => {
  const { t } = useTranslation('crop-health');
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [cropCtx, setCropCtx] = useState<CropContext | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!parcelId) return;
    setLoading(true);

    const fetchData = async () => {
      try {
        const [aRes, cRes] = await Promise.allSettled([
          cropHealthFetch<{ assessments: Assessment[] }>(`/assessments/latest?parcelId=${parcelId}`),
          fetch(`${CROP_CONTEXT_URL}?parcel_id=${parcelId}`, {
            credentials: 'include',
            headers: authHeaders(),
          }).then(r => r.ok ? r.json() : null),
        ]);

        const a = aRes.status === 'fulfilled' ? aRes.value?.assessments?.[0] : null;
        if (a) setAssessment(a);

        const c = cRes.status === 'fulfilled' ? cRes.value : null;
        if (c) setCropCtx(c);
      } catch { /* degrade gracefully */ }
      finally { setLoading(false); }
    };

    fetchData();
  }, [parcelId]);

  if (loading) {
    return (
      <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3 animate-pulse space-y-2">
        <div className="h-4 bg-nkz-border rounded w-3/4" />
        <div className="h-3 bg-nkz-border rounded w-1/2" />
        <div className="h-3 bg-nkz-border rounded w-2/3" />
      </div>
    );
  }

  if (!assessment) {
    return (
      <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3 text-center">
        <span className="text-xl">🌱</span>
        <p className="text-sm text-nkz-text-muted">{t('summary.noData')}</p>
        <p className="text-xs text-nkz-text-muted mt-1">{t('summary.noDataHint')}</p>
      </div>
    );
  }

  const cropName = assessment.cropName || cropCtx?.crop?.name || cropCtx?.crop?.eppo;
  const varietyName = assessment.varietyName || cropCtx?.variety?.name;
  const stage = assessment.phenologyStage || cropCtx?.phenology?.stage;
  const gddVal = assessment.gddAccumulated ?? cropCtx?.season?.gdd_accumulated;
  const stageMin = cropCtx?.phenology?.stage_gdd_min;
  const stageMax = cropCtx?.phenology?.stage_gdd_max;
  const gddPct = gddProgress(gddVal, stageMin, stageMax);

  const cwsi = assessment.cwsiValue;
  const balance = assessment.waterBalanceDeficit;
  const vigor = assessment.vigorIndex;

  const fidelity = assessment.dataFidelity || 'regional_proxy';
  const chips: { icon: string; text: string; intent?: 'positive' | 'warning' | 'negative' }[] = [];

  if (cwsi != null && cwsi >= 0.2) {
    chips.push({ icon: '⚠️', text: t(cwsiPhrase(cwsi)), intent: cwsi > 0.6 ? 'negative' : 'warning' });
  }
  if (balance != null && balance < 0) {
    chips.push({ icon: '💧', text: `${Math.abs(balance).toFixed(1)}mm deficit`, intent: balance < -15 ? 'negative' : 'warning' });
  }
  if (assessment.mdsSeverity && assessment.mdsSeverity !== 'LOW' && assessment.mdsValue != null) {
    chips.push({ icon: '📏', text: `${assessment.mdsValue.toFixed(0)}µm ${assessment.mdsSeverity}`, intent: assessment.mdsSeverity === 'CRITICAL' ? 'negative' : 'warning' });
  }
  if (assessment.thermalCondition && assessment.thermalCondition !== 'no_stress') {
    chips.push({ icon: assessment.thermalCondition?.startsWith('frost') ? '❄️' : '🔥', text: t(assessment.thermalCondition?.startsWith('frost') ? 'summary.thermal.frost' : 'summary.thermal.heat') });
  } else if (assessment.thermalCondition === 'no_stress') {
    chips.push({ icon: '✅', text: t('summary.thermal.none') });
  }
  if (vigor != null && vigor < 0.7) {
    chips.push({ icon: '🌿', text: `${t(vigor >= 0.4 ? 'summary.vigor.below' : 'summary.vigor.low', { value: vigor.toFixed(2) })}`, intent: vigor >= 0.4 ? 'warning' : 'negative' });
  }

  return (
    <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3 shadow-sm">
      {/* Header: severity + action */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <SeverityBadge severity={assessment.overallSeverity} />
          <span className="text-sm font-semibold text-nkz-text-primary">
            {t(actionLabelKey(assessment.recommendedAction))}
          </span>
        </div>
        <FidelityBadge fidelity={fidelity} />
      </div>

      {/* Identity & Phenology */}
      <div className="space-y-1 mb-2">
        {(cropName || parcelName) && (
          <p className="text-sm text-nkz-text-primary">
            {cropName && <span>🌾 <strong>{cropName}</strong>{varietyName ? ` — var. ${varietyName}` : ''}</span>}
            {parcelName && <span className="ml-2 text-nkz-text-muted">📍 {parcelName}</span>}
          </p>
        )}
        {stage && (
          <p className="text-xs text-nkz-text-secondary">
            🌸 {t('summary.phaseLabel')}: <strong>{t(`phenology.stage.${stage}`, stage)}</strong>
            {gddPct != null && <span> · GDD {gddPct.toFixed(0)}%</span>}
          </p>
        )}
      </div>

      {/* Metric chips */}
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {chips.map((c, i) => <MetricChip key={i} {...c} />)}
        </div>
      )}

      {/* Soil reservoir */}
      {assessment.soilWaterBalance && assessment.soilWaterBalance.stressLevel !== 'none' && (
        <div className="pt-2 border-t border-nkz-border">
          <p className="text-xs text-nkz-text-muted">
            🪣 {t('soil.reservoir.' + assessment.soilWaterBalance.stressLevel, {
              current: assessment.soilWaterBalance.swMm.toFixed(0),
              capacity: assessment.soilWaterBalance.awcMm.toFixed(0),
              ratio: (assessment.soilWaterBalance.swRatio * 100).toFixed(0),
            })}
          </p>
        </div>
      )}

      {/* Waterlogging risk */}
      {assessment.waterloggingRisk && assessment.waterloggingRisk.riskLevel !== 'LOW' && (
        <div className="mt-1">
          <p className="text-xs" style={{ color: 'var(--nkz-color-info)' }}>
            💦 {t('waterlogging.' + assessment.waterloggingRisk.riskLevel, { hours: assessment.waterloggingRisk.saturationHours.toFixed(0) })}
          </p>
        </div>
      )}

      {/* Timestamp */}
      {assessment.assessedAt && (
        <p className="text-xs text-nkz-text-muted mt-2 pt-2 border-t border-nkz-border">
          {t('summary.updated')}: {new Date(assessment.assessedAt).toLocaleString()}
        </p>
      )}
    </div>
  );
};

export default CropStatusSnapshot;
