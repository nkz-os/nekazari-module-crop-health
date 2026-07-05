import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Mountain } from 'lucide-react';
import { SlotShell } from '@nekazari/viewer-kit';
import { cropHealthFetch, navigateToCropHealthParcel } from '../api/cropHealthApi';
import { CROP_HEALTH_ACCENT } from '../constants';

interface CompactionRiskData {
  riskLevel: string;
  riskScore: number;
  contributingFactors: string[];
  moistureWarning: boolean;
  vigorConcern: boolean;
  requiresFieldVerification: boolean;
  advisory: string;
  parcelId: string;
  parcelName?: string;
}

const RISK_BAR: Record<string, string> = {
  low: 'bg-green-500',
  moderate: 'bg-amber-500',
  high: 'bg-orange-500',
  very_high: 'bg-red-500',
};

const CompactionRiskWidget: React.FC = () => {
  const { t } = useTranslation('crop-health');
  const [risks, setRisks] = useState<CompactionRiskData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchRisks = async () => {
      const data = await cropHealthFetch<{ assessments: Array<Record<string, unknown>> }>('/assessments/latest');
      const assessments = data?.assessments ?? [];
      const compactionRisks: CompactionRiskData[] = assessments
        .filter((a) => a.compactionRiskLevel || a.compactionRisk)
        .map((a) => {
          const cr = a.compactionRisk as Record<string, unknown> | undefined;
          return {
            riskLevel: String(a.compactionRiskLevel ?? cr?.level ?? ''),
            riskScore: Number(a.compactionRiskScore ?? cr?.score ?? 0),
            contributingFactors: (a.compactionRiskFactors as string[]) ?? (cr?.factors as string[]) ?? [],
            moistureWarning: Boolean(a.compactionMoistureWarning ?? cr?.moistureWarning),
            vigorConcern: Boolean(a.compactionVigorConcern ?? cr?.vigorConcern),
            requiresFieldVerification: Boolean(a.compactionRequiresVerification ?? cr?.requiresVerification ?? true),
            advisory: String(cr?.advisory ?? a.advisory ?? 'normal_management'),
            parcelId: String(a.parcelId ?? ''),
            parcelName: a.parcelName as string | undefined,
          };
        });
      setRisks(compactionRisks);
      setLoading(false);
    };

    fetchRisks();
    const interval = setInterval(fetchRisks, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return null;
  if (!risks.length) return null;

  return (
    <SlotShell moduleId="crop-health" title={t('compaction.title')} icon={<Mountain className="w-4 h-4" />} accent={CROP_HEALTH_ACCENT}>
      <div className="space-y-2">
        {risks.map((r, i) => (
          <div key={i} className="bg-nkz-surface border border-nkz-border rounded-lg p-2.5">
            <div className="flex items-center justify-between gap-2">
              <button
                type="button"
                className="text-sm font-semibold text-nkz-text-primary hover:text-nkz-accent-base truncate bg-transparent border-none cursor-pointer p-0"
                onClick={() => r.parcelId && navigateToCropHealthParcel(r.parcelId)}
              >
                {r.parcelName || r.parcelId}
              </button>
              <span className="text-xs font-medium text-nkz-text-secondary">{t(`compaction.level.${r.riskLevel}`)}</span>
            </div>
            <div className="mt-2 flex items-center gap-2">
              <div className="flex-1 h-1.5 bg-nkz-border rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${RISK_BAR[r.riskLevel] || 'bg-nkz-accent-base'}`} style={{ width: `${Math.min(r.riskScore, 100)}%` }} />
              </div>
              <span className="text-xs font-mono">{r.riskScore.toFixed(0)}%</span>
            </div>
            <p className="text-xs text-nkz-text-muted mt-1">
              {t(`compaction.advisory.${r.advisory}`, r.advisory)}
            </p>
          </div>
        ))}
      </div>
    </SlotShell>
  );
};

export default CompactionRiskWidget;
