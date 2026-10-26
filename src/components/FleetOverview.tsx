import React from 'react';
import { useTranslation } from '@nekazari/sdk';

export interface FleetSummary {
  surprises: number;
  jobsToday: number;
  noData: number;
}

interface FleetOverviewProps {
  summary: FleetSummary;
}

const FleetOverview: React.FC<FleetOverviewProps> = ({ summary }) => {
  const { t } = useTranslation('crop-health');

  const cards = [
    { key: 'surprises', value: summary.surprises, label: t('fleet.surprises'), intent: summary.surprises > 0 ? 'text-nkz-warning' : 'text-nkz-text-muted' },
    { key: 'jobsToday', value: summary.jobsToday, label: t('fleet.jobsToday'), intent: summary.jobsToday > 0 ? 'text-nkz-accent-strong' : 'text-nkz-text-muted' },
    { key: 'noData', value: summary.noData, label: t('fleet.noData'), intent: 'text-nkz-text-muted' },
  ];

  return (
    <div className="grid grid-cols-3 gap-2 p-2 border-b border-nkz-border bg-nkz-surface">
      {cards.map((card) => (
        <div key={card.key} className="rounded-lg border border-nkz-border bg-nkz-surface-raised px-2.5 py-2">
          <p className={`text-lg font-semibold tabular-nums ${card.intent}`}>{card.value}</p>
          <p className="text-xs text-nkz-text-muted leading-tight">{card.label}</p>
        </div>
      ))}
    </div>
  );
};

export default FleetOverview;
