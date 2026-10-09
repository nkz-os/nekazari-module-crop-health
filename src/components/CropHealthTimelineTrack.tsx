import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation, type TimelineTrackProps } from '@nekazari/sdk';
import { DAY_MS, TimelineSparkline, TimelineTrackRow, latestAtOrBefore } from '@nekazari/viewer-kit';
import { CROP_HEALTH_ACCENT } from '../constants';
import type { HistoryPoint } from '../types/assessment';
import { fetchAssessmentHistory, parcelIdFromEntityId, toDailyPoints } from '../utils/assessmentHistory';

/** A value older than this before the cursor is not shown as "the value at the cursor". */
const MAX_VALUE_AGE_MS = 7 * DAY_MS;
const NO_VALUE = '–';

/**
 * Composite stress of the selected parcel along the shared viewer time axis.
 * Reads the cursor, never writes it.
 */
const CropHealthTimelineTrack: React.FC<TimelineTrackProps> = ({ entityId, range, cursor }) => {
  const { t } = useTranslation('crop-health');
  const parcelId = parcelIdFromEntityId(entityId);
  const [history, setHistory] = useState<HistoryPoint[]>([]);

  useEffect(() => {
    let cancelled = false;
    setHistory([]);
    void fetchAssessmentHistory(parcelId, range.start, range.end).then((points) => {
      if (!cancelled) setHistory(points);
    });
    return () => {
      cancelled = true;
    };
  }, [parcelId, range.start, range.end]);

  const points = useMemo(
    () =>
      toDailyPoints(history)
        .filter((p) => p.composite != null)
        .map((p) => ({ time: p.time, value: p.composite as number })),
    [history],
  );

  const atCursor = latestAtOrBefore(points, (p) => p.time, cursor);
  const valueText =
    atCursor && cursor - atCursor.time <= MAX_VALUE_AGE_MS ? atCursor.value.toFixed(2) : NO_VALUE;
  const name = t('timeline.trackLabel');

  const label = (
    <span style={{ display: 'flex', gap: 4, minWidth: 0 }} title={name}>
      <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
      <span style={{ flexShrink: 0, fontWeight: 600 }}>{valueText}</span>
    </span>
  );

  return (
    <TimelineTrackRow label={label} range={range} cursor={cursor}>
      <TimelineSparkline range={range} points={points} valueRange={[0, 1]} color={CROP_HEALTH_ACCENT.base} />
    </TimelineTrackRow>
  );
};

export default CropHealthTimelineTrack;
