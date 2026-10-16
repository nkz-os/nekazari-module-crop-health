import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { SeverityBadge } from './shared/SeverityBadge';
import type { ZoneAssessmentData } from '../types/assessment';
import { zoneKey, zoneNumbers, zoneSelection, type ZoneRef } from '../utils/zones';

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
  // Same numbers as the map labels; rows listed in that order.
  const numbers = useMemo(() => zoneNumbers(zones), [zones]);
  const ordered = useMemo(
    () => [...zones].sort((a, b) => (numbers.get(zoneKey(a.parcelId, a.zoneId)) ?? 0) - (numbers.get(zoneKey(b.parcelId, b.zoneId)) ?? 0)),
    [zones, numbers],
  );
  const [selected, setSelected] = useState<ZoneRef | null>(zoneSelection.get());
  useEffect(() => zoneSelection.subscribe(setSelected), []);
  // Leaving the parcel (or the panel) must not leave a zone lit on the map.
  useEffect(() => () => zoneSelection.pin(null), []);

  if (isWholeParcel || zones.length === 0) {
    return null;
  }

  return (
    <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3">
      <div className="flex items-center justify-between gap-2 mb-2">
        <h3 className="text-sm font-semibold text-nkz-text-primary">{t('zones.title')}</h3>
        <span className="text-xs text-nkz-text-muted">{t('zones.count', { count: zones.length })}</span>
      </div>
      <p className="text-xs text-nkz-text-muted mb-1">{t('zones.hint')}</p>
      <p className="text-xs text-nkz-text-muted mb-3">{t('zones.selectHint')}</p>

      <div className="space-y-2">
        {ordered.map((zone) => {
          const ref = { parcelId: zone.parcelId ?? '', zoneId: zone.zoneId };
          const isSelected = selected?.parcelId === ref.parcelId && selected?.zoneId === ref.zoneId;
          return (
          <button
            type="button"
            key={zone.zoneId}
            aria-pressed={isSelected}
            onMouseEnter={() => zoneSelection.hover(ref)}
            onMouseLeave={() => zoneSelection.hover(null)}
            onFocus={() => zoneSelection.hover(ref)}
            onBlur={() => zoneSelection.hover(null)}
            onClick={() => zoneSelection.pin(ref)}
            className={`w-full text-left rounded-lg border p-3 bg-nkz-surface flex items-start justify-between gap-3 cursor-pointer ${
              isSelected ? 'border-nkz-accent-base' : 'border-nkz-border'
            }`}
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-semibold text-nkz-text-primary">
                  {t('zones.zoneLabel', { id: numbers.get(zoneKey(zone.parcelId, zone.zoneId)) ?? zone.zoneId })}
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
          </button>
          );
        })}
      </div>
    </div>
  );
};

export default ZoneHealthPanel;
