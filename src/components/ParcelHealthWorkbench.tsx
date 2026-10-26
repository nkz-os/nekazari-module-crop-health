import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import SourceStatusPanel from './SourceStatusPanel';
import CropStatusSnapshot from './CropStatusSnapshot';
import PhenologyTimeline from './PhenologyTimeline';
import CropHealthDetailTabs from './CropHealthDetailTabs';
import NoActiveCropCard from './NoActiveCropCard';
import { useParcelHealthData } from '../hooks/useParcelHealthData';

interface ParcelHealthWorkbenchProps {
  parcelId: string;
  parcelName?: string;
}

const ParcelHealthWorkbench: React.FC<ParcelHealthWorkbenchProps> = ({ parcelId, parcelName }) => {
  const { t } = useTranslation('crop-health');
  const data = useParcelHealthData(parcelId);

  if (data.loading) {
    return (
      <div className="space-y-3 animate-pulse">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 h-20" />
        ))}
      </div>
    );
  }

  if (data.error) {
    return (
      <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-4 text-center">
        <p className="text-sm text-nkz-text-muted">{t('error')}: {data.error}</p>
        <button
          type="button"
          className="text-xs text-nkz-accent-base underline mt-2 bg-transparent border-none cursor-pointer"
          onClick={() => void data.refresh()}
        >
          {t('retry')}
        </button>
      </div>
    );
  }

  if (data.cropStatus === 'none') {
    return (
      <div className="space-y-0">
        <NoActiveCropCard
          parcelId={parcelId}
          plannedCrop={data.plannedCrop}
          lastAssessment={
            data.assessment
              ? { assessedAt: data.assessment.assessedAt, cropName: data.assessment.cropName }
              : null
          }
        />
        <SourceStatusPanel parcelId={parcelId} parcelName={parcelName} embedded defaultOpen={false} />
      </div>
    );
  }

  return (
    <div className="space-y-0">
      <CropStatusSnapshot
        parcelId={parcelId}
        parcelName={parcelName}
        assessment={data.assessment as never}
        nextJob={data.nextJob}
        surprise={data.surprise}
        freshness={data.freshness}
        stale={data.stale}
      />
      <PhenologyTimeline status={data.phenologyStatus} />
      <CropHealthDetailTabs
        parcelId={parcelId}
        assessment={data.assessment}
        phenology={data.phenologyParams}
        trend={data.trend}
        correlation={data.correlation}
        correlationStats={data.correlationStats}
        diseases={data.diseases}
        zones={data.zoneAssessments}
        isWholeParcel={data.isWholeParcel}
        parcelValues={data.parcelValues}
      />
      <SourceStatusPanel parcelId={parcelId} parcelName={parcelName} embedded defaultOpen={false} />
    </div>
  );
};

export default ParcelHealthWorkbench;
