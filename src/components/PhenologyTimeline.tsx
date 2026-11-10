import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import type { PhenologyStageProjection, PhenologyStatus } from '../types/assessment';
import PhenologyModelInfo from './phenology/PhenologyModelInfo';
import PhenologyMilestones from './phenology/PhenologyMilestones';
import PhenologyValidation from './phenology/PhenologyValidation';
import PhenologyObservations from './phenology/PhenologyObservations';
import ObservedStageForm from './phenology/ObservedStageForm';

interface PhenologyTimelineProps {
  status: PhenologyStatus | null;
  /** Parcel the observed-stage form records against (form hidden without it). */
  parcelId?: string;
  /** Called after an observed stage was recorded, to refresh the status. */
  onRecorded?: () => void;
}

function stageStatusClass(status: string): string {
  switch (status) {
    case 'current':
      return 'border-nkz-accent-base bg-nkz-accent-soft text-nkz-accent-strong';
    case 'completed':
      return 'border-nkz-success bg-nkz-success-soft text-nkz-success-strong';
    case 'upcoming':
      return 'border-nkz-border bg-nkz-surface text-nkz-text-muted';
    default:
      return 'border-nkz-border bg-nkz-surface-raised text-nkz-text-secondary';
  }
}

// The backend emits `current`/`reached` booleans (not a `status` string).
function deriveStageStatus(stage: PhenologyStageProjection): 'current' | 'completed' | 'upcoming' {
  if (stage.current) return 'current';
  if (stage.reached) return 'completed';
  return 'upcoming';
}

const PhenologyTimeline: React.FC<PhenologyTimelineProps> = ({ status, parcelId, onRecorded }) => {
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

      <PhenologyModelInfo status={status} />

      <div className="flex gap-1 overflow-x-auto pb-1">
        {status.stages.map((stage) => {
          const stageStatus = deriveStageStatus(stage);
          return (
            <div
              key={stage.stage}
              className={`min-w-[88px] flex-shrink-0 rounded-md border px-2 py-1.5 text-center ${stageStatusClass(stageStatus)}`}
            >
              <p className="text-[11px] font-medium leading-tight">
                {t(`phenology.stage.${stage.stage}`, stage.stage)}
              </p>
              {status.model && stage.bbchFrom != null && stage.bbchTo != null && (
                <p className="text-[10px] opacity-80">
                  {t('phenologyTimeline.bbchRange', { from: stage.bbchFrom, to: stage.bbchTo })}
                </p>
              )}
              {stage.projectedDate && (
                <p className="text-[10px] opacity-80 mt-0.5">{stage.projectedDate.slice(5)}</p>
              )}
            </div>
          );
        })}
      </div>

      {status.deviation && status.deviation !== 'on_track' && (
        <p className="text-xs text-nkz-warning-strong mt-2">
          {t('phenologyTimeline.deviation', { value: status.deviation })}
        </p>
      )}

      {status.model && (
        <>
          <PhenologyMilestones status={status} />
          <PhenologyValidation status={status} />
          <PhenologyObservations status={status} />
          {parcelId && <ObservedStageForm parcelId={parcelId} onRecorded={onRecorded} />}
          <p className="text-[10px] text-nkz-text-muted mt-3">{t('phenologyTimeline.bbchAttribution')}</p>
        </>
      )}
    </div>
  );
};

export default PhenologyTimeline;
