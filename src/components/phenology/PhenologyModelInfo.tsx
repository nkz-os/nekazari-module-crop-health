import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge } from '@nekazari/ui-kit';
import type { PhenologyStatus } from '../../types/assessment';

function regionName(status: PhenologyStatus): string | null {
  const r = status.calibration?.region;
  if (!r) return null;
  return typeof r === 'string' ? r : r.name ?? r.id ?? null;
}

/** Experimental badge plus the model (and calibration region) the dates come from. */
const PhenologyModelInfo: React.FC<{ status: PhenologyStatus }> = ({ status }) => {
  const { t } = useTranslation('crop-health');
  const m = status.model;
  if (!m) return null;
  const model = [m.cultivar ?? m.id, m.version].filter(Boolean).join(' ');
  const region = regionName(status);
  return (
    <div className="flex flex-wrap items-center gap-2 mb-2">
      <Badge intent="warning">{t('phenologyTimeline.experimental')}</Badge>
      <p className="text-xs text-nkz-text-secondary">
        {status.calibration?.status === 'calibrated' && region
          ? t('phenologyTimeline.modelCalibrated', { model, region })
          : t('phenologyTimeline.model', { model })}
      </p>
    </div>
  );
};

export default PhenologyModelInfo;
