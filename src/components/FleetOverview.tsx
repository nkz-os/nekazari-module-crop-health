import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { cropHealthFetch } from '../api/cropHealthApi';
import type { AssessmentData, ParcelSummary } from '../types/assessment';

interface FleetStats {
  total: number;
  withData: number;
  critical: number;
  high: number;
  irrigateNow: number;
  noData: number;
}

interface FleetOverviewProps {
  parcels: ParcelSummary[];
  assessments: AssessmentData[];
  diseaseCount: number;
}

const FleetOverview: React.FC<FleetOverviewProps> = ({ parcels, assessments, diseaseCount }) => {
  const { t } = useTranslation('crop-health');

  const stats: FleetStats = useMemo(() => {
    const critical = parcels.filter((p) => p.overallSeverity === 'CRITICAL').length;
    const high = parcels.filter((p) => p.overallSeverity === 'HIGH').length;
    const irrigateNow = assessments.filter((a) => a.recommendedAction === 'IRRIGATE_IMMEDIATE').length;
    return {
      total: parcels.length,
      withData: parcels.filter((p) => p.hasData).length,
      critical,
      high,
      irrigateNow,
      noData: parcels.filter((p) => !p.hasData).length,
    };
  }, [parcels, assessments]);

  const cards = [
    {
      key: 'monitored',
      value: stats.withData,
      suffix: `/ ${stats.total}`,
      label: t('fleet.monitored'),
      intent: 'text-nkz-text-primary',
    },
    {
      key: 'critical',
      value: stats.critical + stats.high,
      label: t('fleet.stressed'),
      intent: stats.critical + stats.high > 0 ? 'text-red-600' : 'text-nkz-text-muted',
    },
    {
      key: 'irrigate',
      value: stats.irrigateNow,
      label: t('fleet.irrigateNow'),
      intent: stats.irrigateNow > 0 ? 'text-orange-600' : 'text-nkz-text-muted',
    },
    {
      key: 'disease',
      value: diseaseCount,
      label: t('fleet.diseaseAlerts'),
      intent: diseaseCount > 0 ? 'text-amber-600' : 'text-nkz-text-muted',
    },
    {
      key: 'pending',
      value: stats.noData,
      label: t('fleet.pendingSetup'),
      intent: stats.noData > 0 ? 'text-nkz-accent-strong' : 'text-nkz-text-muted',
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 p-2 border-b border-nkz-border bg-nkz-surface">
      {cards.map((card) => (
        <div key={card.key} className="rounded-lg border border-nkz-border bg-nkz-surface-raised px-2.5 py-2">
          <p className={`text-lg font-semibold tabular-nums ${card.intent}`}>{card.value}{card.suffix ?? ''}</p>
          <p className="text-xs text-nkz-text-muted leading-tight">{card.label}</p>
        </div>
      ))}
    </div>
  );
};

export function useFleetAssessments(): AssessmentData[] {
  const [assessments, setAssessments] = useState<AssessmentData[]>([]);

  useEffect(() => {
    cropHealthFetch<{ assessments: AssessmentData[] }>('/assessments/latest').then((data) => {
      setAssessments(data?.assessments ?? []);
    });
  }, []);

  return assessments;
}

export function useActiveDiseaseCount(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    cropHealthFetch<{ risks: unknown[] }>('/diseases/active').then((data) => {
      setCount(data?.risks?.length ?? 0);
    });
  }, []);

  return count;
}

export default FleetOverview;
