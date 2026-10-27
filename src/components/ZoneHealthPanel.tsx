import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { SeverityBadge } from './shared/SeverityBadge';
import type { ZoneAssessmentData, ZonesResponse } from '../types/assessment';
import { navigateTo } from '../api/cropHealthApi';
import { fidelityLine, splitZones, zoneKey, zoneNumberList, zoneNumbers, zoneSelection, zoneViewerPath, type ZoneRef } from '../utils/zones';

interface ZoneHealthPanelProps {
  zones: ZoneAssessmentData[];
  isWholeParcel: boolean;
  parcelValues?: ZonesResponse['parcelValues'];
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
  // compositeStressIndex is already on a 0-100 scale (engines/composite.py).
  if (zone.compositeStressIndex != null) return `${Math.round(zone.compositeStressIndex)}%`;
  if (zone.vigorIndex != null) return `VHI ${Math.round(zone.vigorIndex * 100)}`;
  return '—';
}

// The parcel's value for the same metric the zone row shows.
function parcelMetricLabel(zone: ZoneAssessmentData, pv: ZonesResponse['parcelValues']): string {
  if (zone.cwsiValue != null) return pv.cwsiValue != null ? `CWSI ${pv.cwsiValue.toFixed(2)}` : '—';
  if (zone.compositeStressIndex != null) return pv.compositeStressIndex != null ? `${Math.round(pv.compositeStressIndex)}%` : '—';
  if (zone.vigorIndex != null) return pv.vigorIndex != null ? `VHI ${Math.round(pv.vigorIndex * 100)}` : '—';
  return '—';
}

function provenance(zone: ZoneAssessmentData, t: (key: string) => string): React.ReactNode {
  const { own, inherited } = fidelityLine(zone.inputFidelity, t);
  if (own.length === 0 && inherited.length === 0) return null;
  const parts: string[] = [];
  if (own.length > 0) parts.push(`${t('zones.fidelity.own')}: ${own.join(' · ')}`);
  if (inherited.length > 0) parts.push(`${t('zones.fidelity.inherited')}: ${inherited.join(' · ')}`);
  return <p className="text-xs text-nkz-text-muted mt-1">{parts.join(' — ')}</p>;
}

const ZoneHealthPanel: React.FC<ZoneHealthPanelProps> = ({ zones, isWholeParcel, parcelValues = {} }) => {
  const { t } = useTranslation('crop-health');
  // Same numbers as the map labels; rows listed in that order.
  const numbers = useMemo(() => zoneNumbers(zones), [zones]);
  const { differing, rest } = useMemo(() => splitZones(zones), [zones]);
  const ordered = useMemo(
    () => [...differing].sort((a, b) => (numbers.get(zoneKey(a.parcelId, a.zoneId)) ?? 0) - (numbers.get(zoneKey(b.parcelId, b.zoneId)) ?? 0)),
    [differing, numbers],
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
      {differing.length === 0 ? (
        <p className="text-xs text-nkz-text-muted">{t('zones.noDifference', { count: zones.length })}</p>
      ) : (
        <>
          <p className="text-xs text-nkz-text-muted mb-3">{t('zones.hint')}</p>
          <div className="space-y-2">
            {ordered.map((zone) => {
              const ref = { parcelId: zone.parcelId ?? '', zoneId: zone.zoneId };
              const isSelected = selected?.parcelId === ref.parcelId && selected?.zoneId === ref.zoneId;
              return (
                <div
                  key={zone.zoneId}
                  onMouseEnter={() => zoneSelection.hover(ref)}
                  onMouseLeave={() => zoneSelection.hover(null)}
                  className={`w-full rounded-lg border p-3 bg-nkz-surface flex items-start justify-between gap-3 ${
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
                      {zone.wetnessClass && (
                        <span
                          className="text-[10px] uppercase tracking-wide text-nkz-text-muted font-medium"
                          title={t(`zones.wetness.${zone.wetnessClass}`)}
                          aria-label={t(`zones.wetness.${zone.wetnessClass}`)}
                        >
                          {t(`zones.wetness.${zone.wetnessClass}`)}
                        </span>
                      )}
                      <SeverityBadge severity={zone.overallSeverity} />
                    </div>
                    <p className="text-xs text-nkz-text-muted mt-1">
                      {t('zones.metric')}: {metricLabel(zone)} · {t('zones.parcelValue', { value: parcelMetricLabel(zone, parcelValues) })}
                      {zone.dominantStressor && zone.dominantStressor !== 'none' && (
                        <> · {t('zones.stressor', { value: zone.dominantStressor })}</>
                      )}
                    </p>
                    {provenance(zone, t)}
                    {zone.recommendedAction && zone.recommendedAction !== 'NO_ACTION' && (
                      <p className="text-xs text-nkz-text-secondary mt-1">
                        {t(actionLabelKey(zone.recommendedAction), zone.recommendedAction)}
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    onFocus={() => zoneSelection.hover(ref)}
                    onBlur={() => zoneSelection.hover(null)}
                    onClick={() => {
                      zoneSelection.pin(ref);
                      navigateTo(zoneViewerPath(ref));
                    }}
                    className="text-xs text-nkz-accent-base font-medium cursor-pointer"
                  >
                    {t('zones.showOnMap')}
                  </button>
                </div>
              );
            })}
          </div>
        </>
      )}
      {differing.length > 0 && rest.length > 0 && (
        <p className="text-xs text-nkz-text-muted mt-3">{t('zones.rest', { list: zoneNumberList(rest, numbers) })}</p>
      )}
    </div>
  );
};

export default ZoneHealthPanel;
