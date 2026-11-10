import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import type { PhenologyMilestone, PhenologyStatus } from '../../types/assessment';
import { MILESTONE_ORDER } from './phenologyBbch';

const MilestoneValue: React.FC<{ m: PhenologyMilestone }> = ({ m }) => {
  const { t } = useTranslation('crop-health');
  if (m.status === 'reached' && m.date) {
    return <>{t('phenologyTimeline.milestoneReached', { date: m.date })}</>;
  }
  if (m.status === 'projected' && m.date_p50) {
    return m.date_p10 && m.date_p90
      ? <>{t('phenologyTimeline.milestoneProjected', { p50: m.date_p50, p10: m.date_p10, p90: m.date_p90 })}</>
      : <>{t('phenologyTimeline.milestoneProjectedNoRange', { p50: m.date_p50 })}</>;
  }
  return <>{t('phenologyTimeline.milestoneUnavailable', { reason: m.reason ?? m.status })}</>;
};

/** Milestone dates exactly as the engine returned them; nothing is filled in. */
const PhenologyMilestones: React.FC<{ status: PhenologyStatus }> = ({ status }) => {
  const { t } = useTranslation('crop-health');
  const milestones = status.milestones;
  if (!milestones) return null;
  const rows = MILESTONE_ORDER.filter((k) => milestones[k]);
  if (!rows.length) return null;
  return (
    <div className="mt-3">
      <p className="text-xs font-semibold text-nkz-text-primary mb-1">{t('phenologyTimeline.milestones')}</p>
      <ul className="space-y-0.5">
        {rows.map((k) => (
          <li key={k} className="text-xs text-nkz-text-secondary">
            <span className="font-medium text-nkz-text-primary">{t(`phenologyTimeline.milestone.${k}`)}</span>
            {': '}
            <MilestoneValue m={milestones[k]!} />
          </li>
        ))}
      </ul>
      {status.basis === 'thermal_time' && (
        <p className="text-xs text-nkz-text-muted mt-1">{t('phenologyTimeline.basisThermalTime')}</p>
      )}
    </div>
  );
};

export default PhenologyMilestones;
