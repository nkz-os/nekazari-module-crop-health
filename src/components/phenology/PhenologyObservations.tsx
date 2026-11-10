import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import type { PhenologyStatus } from '../../types/assessment';

/** Field observations next to what the model gave that day. */
const PhenologyObservations: React.FC<{ status: PhenologyStatus }> = ({ status }) => {
  const { t } = useTranslation('crop-health');
  const rows = status.observations;
  if (!status.model || !rows?.length) return null;
  const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  return (
    <div className="mt-3">
      <p className="text-xs font-semibold text-nkz-text-primary mb-1">{t('phenologyTimeline.observations.title')}</p>
      <ul className="space-y-1">
        {sorted.map((o) => (
          <li key={`${o.date}-${o.bbch}`} className="text-xs text-nkz-text-secondary">
            <span className="font-medium text-nkz-text-primary">{o.date}</span>
            {' · '}
            {t('phenologyTimeline.observations.bbch', { code: o.bbch })}
            {o.stage ? ` (${t(`phenology.stage.${o.stage}`, o.stage)})` : ''}
            {' · '}
            {t('phenologyTimeline.observations.modelStage', {
              stage: o.modelStageOnDate ? t(`phenology.stage.${o.modelStageOnDate}`, o.modelStageOnDate) : t('phenologyTimeline.observations.none'),
            })}
            {o.deltaDays != null && (
              <>
                {' · '}
                {o.deltaDays === 0
                  ? t('phenologyTimeline.observations.sameDay')
                  : o.deltaDays < 0
                    ? t('phenologyTimeline.observations.modelEarlier', { count: Math.abs(o.deltaDays) })
                    : t('phenologyTimeline.observations.modelLater', { count: o.deltaDays })}
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
};

export default PhenologyObservations;
