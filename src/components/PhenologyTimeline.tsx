import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import type { PhenologyStatus } from '../types/assessment';

interface PhenologyTimelineProps {
  status: PhenologyStatus | null;
}

function stageStatusClass(status: string): string {
  switch (status) {
    case 'current':
      return 'border-nkz-accent-base bg-nkz-accent-soft text-nkz-accent-strong';
    case 'completed':
      return 'border-green-300 bg-green-50 text-green-800';
    case 'upcoming':
      return 'border-nkz-border bg-nkz-surface text-nkz-text-muted';
    default:
      return 'border-nkz-border bg-nkz-surface-raised text-nkz-text-secondary';
  }
}

const PhenologyTimeline: React.FC<PhenologyTimelineProps> = ({ status }) => {
  const { t } = useTranslation('crop-health');

  if (!status || status.status === 'pending' || !status.stages?.length) {
    return null;
  }

  return (
    <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-nkz-text-primary">{t('phenologyTimeline.title')}</h3>
        {status.gdd?.accumulated != null && (
          <span className="text-xs text-nkz-text-muted">
            GDD {status.gdd.accumulated.toFixed(0)}
          </span>
        )}
      </div>

      <div className="flex gap-1 overflow-x-auto pb-1">
        {status.stages.map((stage) => (
          <div
            key={stage.stage}
            className={`min-w-[88px] flex-shrink-0 rounded-md border px-2 py-1.5 text-center ${stageStatusClass(stage.status)}`}
          >
            <p className="text-[11px] font-medium leading-tight">
              {t(`phenology.stage.${stage.stage}`, stage.stage)}
            </p>
            {stage.projectedStart && (
              <p className="text-[10px] opacity-80 mt-0.5">{stage.projectedStart.slice(5)}</p>
            )}
          </div>
        ))}
      </div>

      {status.deviation && status.deviation !== 'on_track' && (
        <p className="text-xs text-amber-700 mt-2">
          {t('phenologyTimeline.deviation', { value: status.deviation })}
        </p>
      )}
    </div>
  );
};

export default PhenologyTimeline;
