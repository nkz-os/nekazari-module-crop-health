import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Bug } from 'lucide-react';
import { SlotShell } from '@nekazari/viewer-kit';
import { cropHealthFetch } from '../api/cropHealthApi';
import { CROP_HEALTH_ACCENT } from '../constants';
import { SeverityBadge } from './shared/SeverityBadge';
import type { DiseaseRisk } from '../types/assessment';

const DISEASE_EMOJIS: Record<string, string> = {
  downy_mildew: '🍇',
  apple_scab: '🍎',
  alternaria: '🍅',
  powdery_mildew: '🌿',
};

const DiseaseRiskWidget: React.FC = () => {
  const { t } = useTranslation('crop-health');
  const [risks, setRisks] = useState<DiseaseRisk[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchRisks = async () => {
      const data = await cropHealthFetch<{ risks: DiseaseRisk[] }>('/diseases/active');
      setRisks(data?.risks ?? []);
      setLoading(false);
    };
    fetchRisks();
    const interval = setInterval(fetchRisks, 30 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <SlotShell moduleId="crop-health" title={t('diseaseRisk')} icon={<Bug className="w-4 h-4" />} accent={CROP_HEALTH_ACCENT}>
        <div className="animate-pulse h-14 bg-nkz-border rounded-lg" />
      </SlotShell>
    );
  }

  if (!risks.length) return null;

  return (
    <SlotShell moduleId="crop-health" title={t('diseaseRisk')} icon={<Bug className="w-4 h-4" />} accent={CROP_HEALTH_ACCENT}>
      <div className="space-y-2">
        {risks.map((r, i) => (
          <div key={i} className="bg-nkz-surface border border-nkz-border rounded-lg p-2.5 border-l-[3px] border-l-amber-500">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold text-nkz-text-primary">
                {(DISEASE_EMOJIS[r.disease] || '🦠')} {t(`disease.${r.disease}`, r.disease)}
              </span>
              <SeverityBadge severity={r.risk_level} />
            </div>
            {(r.crop || r.parcelId) && (
              <p className="text-xs text-nkz-text-muted mt-1">
                {r.crop && <span>🌾 {r.crop}</span>}
                {r.parcelId && <span className="ml-2">📋 {r.parcelId}</span>}
              </p>
            )}
            <p className="text-xs text-nkz-text-secondary mt-1">{r.conditions}</p>
            <p className="text-xs font-semibold text-nkz-text-primary mt-1">
              {t(`disease.action.${r.recommended_action}`, r.recommended_action)}
            </p>
          </div>
        ))}
      </div>
    </SlotShell>
  );
};

export default DiseaseRiskWidget;
