import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { SeverityBadge } from './shared/SeverityBadge';
import type { AssessmentData, DiseaseRisk } from '../types/assessment';

interface CropHealthRisksPanelProps {
  diseases: DiseaseRisk[];
  assessment: AssessmentData | null;
}

const DISEASE_EMOJIS: Record<string, string> = {
  downy_mildew: '🍇',
  apple_scab: '🍎',
  alternaria: '🍅',
  powdery_mildew: '🌿',
};

function riskColor(level: string): string {
  if (level === 'HIGH') return '#dc2626';
  if (level === 'MEDIUM') return '#d97706';
  return '#16a34a';
}

const CropHealthRisksPanel: React.FC<CropHealthRisksPanelProps> = ({ diseases, assessment }) => {
  const { t } = useTranslation('crop-health');
  const compaction = assessment?.compactionRisk;
  const hasCompaction = Boolean(compaction?.level && compaction.level !== 'low');
  const hasDiseases = diseases.length > 0;

  if (!hasDiseases && !hasCompaction) {
    return (
      <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3 text-center">
        <span className="text-xl">🛡️</span>
        <p className="text-sm text-nkz-text-muted mt-1">{t('risks.noneActive')}</p>
      </div>
    );
  }

  return (
    <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3 space-y-3">
      <h3 className="text-sm font-semibold text-nkz-text-primary">{t('risks.title')}</h3>

      {hasDiseases && (
        <div className="space-y-2">
          {diseases.map((r, i) => {
            const color = riskColor(r.risk_level);
            return (
              <div
                key={`${r.disease}-${i}`}
                className="rounded-lg border border-nkz-border p-2.5 border-l-[3px] bg-nkz-surface"
                style={{ borderLeftColor: color }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-nkz-text-primary">
                    {(DISEASE_EMOJIS[r.disease] || '🦠')} {t(`disease.${r.disease}`, r.disease)}
                  </span>
                  <SeverityBadge severity={r.risk_level} />
                </div>
                {r.crop && <p className="text-xs text-nkz-text-muted mt-1">🌾 {r.crop}</p>}
                <p className="text-xs text-nkz-text-secondary mt-1">{r.conditions}</p>
                <p className="text-xs font-semibold mt-1.5" style={{ color }}>
                  {t(`disease.action.${r.recommended_action}`, r.recommended_action)}
                </p>
              </div>
            );
          })}
        </div>
      )}

      {hasCompaction && compaction && (
        <div className="rounded-lg border border-nkz-border p-2.5 border-l-[3px] bg-nkz-surface border-l-orange-500">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-semibold text-nkz-text-primary">🪨 {t('compaction.title')}</span>
            <span className="text-xs font-medium text-orange-700">
              {t(`compaction.level.${compaction.level}`)}
            </span>
          </div>
          <div className="mt-2 flex items-center gap-2">
            <div className="flex-1 h-1.5 bg-nkz-border rounded-full overflow-hidden">
              <div
                className="h-full rounded-full bg-orange-500"
                style={{ width: `${Math.min(compaction.score ?? 0, 100)}%` }}
              />
            </div>
            <span className="text-xs font-mono text-nkz-text-primary">{(compaction.score ?? 0).toFixed(0)}%</span>
          </div>
          {compaction.advisory && (
            <p className="text-xs text-nkz-text-muted mt-1">
              {t(`compaction.advisory.${compaction.advisory}`, compaction.advisory)}
            </p>
          )}
        </div>
      )}
    </div>
  );
};

export default CropHealthRisksPanel;
