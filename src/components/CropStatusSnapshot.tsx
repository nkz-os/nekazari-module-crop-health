import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
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

function balancePhrase(balance: number): string {
  if (balance > 0) return 'summary.balance.positive';
  if (balance >= -5) return 'summary.balance.mild';
  if (balance >= -15) return 'summary.balance.moderate';
  return 'summary.balance.severe';
}

function vigorPhrase(vigor: number): string {
  if (vigor > 0.7) return 'summary.vigor.good';
  if (vigor >= 0.4) return 'summary.vigor.below';
  return 'summary.vigor.low';
}

function thermalPhrase(condition: string | undefined): string | null {
  if (!condition || condition === 'no_stress') return null;
  if (condition.startsWith('frost')) return 'summary.thermal.frost';
  if (condition.startsWith('heat')) return 'summary.thermal.heat';
  return null;
}

function mdsPhrase(severity: string | undefined): string | null {
  if (!severity || severity === 'LOW') return null;
  if (severity === 'MEDIUM') return 'summary.mds.medium';
  if (severity === 'HIGH') return 'summary.mds.high';
  if (severity === 'CRITICAL') return 'summary.mds.critical';
  return null;
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
          fetch(`/api/crop-health/assessments/latest?parcelId=${parcelId}`).then(r => r.ok ? r.json() : null),
          fetch(`/api/bioorchestrator/api/graph/agriculture/crop-context?parcel_id=${parcelId}`).then(r => r.ok ? r.json() : null),
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
      <div className="animate-pulse space-y-2 p-3 bg-nkz-surface-raised rounded mb-3">
        <div className="h-4 bg-nkz-border rounded w-3/4" />
        <div className="h-3 bg-nkz-border rounded w-1/2" />
        <div className="h-3 bg-nkz-border rounded w-2/3" />
      </div>
    );
  }

  if (!assessment) {
    return (
      <div className="text-center p-3 bg-nkz-surface-raised rounded mb-3 border border-nkz-border">
        <span className="text-xl">🌱</span>
        <p className="text-nkz-text-muted text-sm">{t('summary.noData')}</p>
        <p className="text-nkz-text-muted text-xs mt-1">{t('summary.noDataHint')}</p>
      </div>
    );
  }

  // Priority: assessment fields (persisted) > crop-context (live)
  const cropName = assessment.cropName || cropCtx?.crop?.name || cropCtx?.crop?.eppo;
  const varietyName = assessment.varietyName || cropCtx?.variety?.name;
  const stage = assessment.phenologyStage || cropCtx?.phenology?.stage;
  const gddVal = assessment.gddAccumulated ?? cropCtx?.season?.gdd_accumulated;
  const stageMin = cropCtx?.phenology?.stage_gdd_min;
  const stageMax = cropCtx?.phenology?.stage_gdd_max;
  const gddPct = gddProgress(gddVal, stageMin, stageMax);

  const cwsi = assessment.cwsiValue;
  const balance = assessment.waterBalanceDeficit;
  const mdsSev = assessment.mdsSeverity;
  const thermal = assessment.thermalCondition;
  const vigor = assessment.vigorIndex;

  const lines: { icon: string; text: string; color?: string }[] = [];

  // Identity line
  if (cropName) {
    const idLine = varietyName
      ? `🌾 ${cropName} — var. ${varietyName}`
      : `🌾 ${cropName}`;
    lines.push({ icon: '', text: idLine });
  }
  if (parcelName) {
    lines.push({ icon: '📍', text: parcelName });
  }

  // Phenology line
  if (stage) {
    const stageLabel = t(`phenology.stage.${stage}`, stage);
    const gddInfo = gddPct != null ? ` · GDD ${gddPct.toFixed(0)}%` : '';
    lines.push({ icon: '🌸', text: `${t('summary.phaseLabel')}: ${stageLabel}${gddInfo}` });
  }

  // Water stress lines
  if (cwsi != null && cwsi >= 0.2) {
    lines.push({ icon: '⚠️', text: t(cwsiPhrase(cwsi)), color: cwsi > 0.6 ? '#dc2626' : '#d97706' });
  }
  if (balance != null && balance < 0) {
    lines.push({ icon: '💧', text: t(balancePhrase(balance), { value: Math.abs(balance).toFixed(1) }), color: '#dc2626' });
  }
  if (mdsSev) {
    const phrase = mdsPhrase(mdsSev);
    if (phrase) {
      const mdsVal = assessment.mdsValue;
      lines.push({ icon: '📏', text: t(phrase, { value: mdsVal?.toFixed(0) || '?' }), color: '#d97706' });
    }
  }

  // Thermal line
  const tPhrase = thermalPhrase(thermal);
  if (tPhrase) {
    lines.push({ icon: '🌡️', text: t(tPhrase) });
  } else if (thermal === 'no_stress') {
    lines.push({ icon: '✅', text: t('summary.thermal.none') });
  }

  // Vigor line
  if (vigor != null) {
    const vColor = vigor > 0.7 ? '#16a34a' : vigor >= 0.4 ? '#d97706' : '#dc2626';
    lines.push({ icon: '🌿', text: t(vigorPhrase(vigor), { value: vigor.toFixed(2) }), color: vColor });
  }

  // Fidelity
  const fidelity = assessment.dataFidelity || 'regional_proxy';

  return (
    <div className="bg-nkz-surface-raised rounded p-3 mb-3 border border-nkz-border">
      {/* Header: severity + action */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <SeverityBadge severity={assessment.overallSeverity} />
          <span className="text-nkz-text-primary font-semibold text-sm">
            {t(`action.${assessment.recommendedAction === 'NO_ACTION' ? 'noAction' : assessment.recommendedAction === 'MONITOR' ? 'monitor' : assessment.recommendedAction === 'IRRIGATE_SCHEDULED' ? 'irrigateScheduled' : 'irrigateImmediate'}`)}
          </span>
        </div>
        <span className="text-nkz-text-muted text-xs">{t(`summary.fidelity.${fidelity}`, fidelity)}</span>
      </div>

      {/* Narrative lines */}
      {lines.map((line, i) => (
        <p
          key={i}
          className="text-sm leading-relaxed"
          style={{ color: line.color || undefined }}
        >
          {line.icon && <span className="mr-1.5">{line.icon}</span>}
          <span className={line.color ? '' : 'text-nkz-text-primary'}>{line.text}</span>
        </p>
      ))}

      {/* Timestamp */}
      {assessment.assessedAt && (
        <p className="text-nkz-text-muted text-xs mt-2">
          {t('summary.updated')}: {new Date(assessment.assessedAt).toLocaleString()}
        </p>
      )}
    </div>
  );
};

export default CropStatusSnapshot;
