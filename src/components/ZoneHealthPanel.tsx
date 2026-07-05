import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { SeverityBadge } from './shared/SeverityBadge';
import type { ZoneAssessmentData } from '../types/assessment';

interface ZoneHealthPanelProps {
  zones: ZoneAssessmentData[];
  isWholeParcel: boolean;
}

function actionLabelKey(action: string): string {
  switch (action) {
    case 'NO_ACTION':
      return 'action.noAction';
    case 'MONITOR':
      return 'action.monitor';
    case 'IRRIGATE_SCHEDULED':
      return 'action.irrigateScheduled';
    case 'IRRIGATE_IMMEDIATE':
      return 'action.irrigateImmediate';
    default:
      return action;
  }
}

function metricLabel(zone: ZoneAssessmentData): string {
  if (zone.cwsiValue != null) return `CWSI ${zone.cwsiValue.toFixed(2)}`;
  if (zone.compositeStressIndex != null) return `${Math.round(zone.compositeStressIndex * 100)}%`;
  if (zone.vigorIndex != null) return `VHI ${Math.round(zone.vigorIndex * 100)}`;
  return '—';
}

const ZoneHealthPanel: React.FC<ZoneHealthPanelProps> = ({ zones, isWholeParcel }) => {
  const { t } = useTranslation('crop-health');

  if (isWholeParcel || zones.length === 0) {
    return null;
  }

  return (
    <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3">
      <div className="flex items-center justify-between gap-2 mb-2">
        <h3 className="text-sm font-semibold text-nkz-text-primary">{t('zones.title')}</h3>
        <span className="text-xs text-nkz-text-muted">{t('zones.count', { count: zones.length })}</span>
      </div>
      <p className="text-xs text-nkz-text-muted mb-3">{t('zones.hint')}</p>

      <div className="space-y-2">
        {zones.map((zone) => (
          <div
            key={zone.zoneId}
            className="rounded-lg border border-nkz-border p-2.5 bg-nkz-surface flex items-start justify-between gap-3"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-semibold text-nkz-text-primary">
                  {t('zones.zoneLabel', { id: zone.zoneId })}
                </span>
                {zone.sensorNearby && (
                  <span className="text-[10px] uppercase tracking-wide text-nkz-accent-base font-medium">
                    {t('zones.sensorNearby')}
                  </span>
                )}
              </div>
              <p className="text-xs text-nkz-text-muted mt-1">
                {t('zones.metric')}: {metricLabel(zone)}
                {zone.dominantStressor && zone.dominantStressor !== 'none' && (
                  <> · {t('zones.stressor', { value: zone.dominantStressor })}</>
                )}
              </p>
              {zone.recommendedAction && zone.recommendedAction !== 'NO_ACTION' && (
                <p className="text-xs text-nkz-text-secondary mt-1">
                  {t(actionLabelKey(zone.recommendedAction), zone.recommendedAction)}
                </p>
              )}
            </div>
            <SeverityBadge severity={zone.overallSeverity} />
          </div>
        ))}
      </div>
    </div>
  );
};

export default ZoneHealthPanel;
