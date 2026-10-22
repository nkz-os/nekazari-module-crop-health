import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import SourceStatusPanel from './SourceStatusPanel';
import CropStatusSnapshot from './CropStatusSnapshot';
import PhenologyTimeline from './PhenologyTimeline';
import CropHealthRisksPanel from './CropHealthRisksPanel';
import CropHealthDetailTabs from './CropHealthDetailTabs';
import ZoneHealthPanel from './ZoneHealthPanel';
import { useParcelHealthData } from '../hooks/useParcelHealthData';

interface ParcelHealthWorkbenchProps {
  parcelId: string;
  parcelName?: string;
}

const ParcelHealthWorkbench: React.FC<ParcelHealthWorkbenchProps> = ({ parcelId, parcelName }) => {
  const { t } = useTranslation('crop-health');
  const [showDiagnostics, setShowDiagnostics] = useState(true);
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

  return (
    <div className="space-y-0">
      <CropStatusSnapshot parcelId={parcelId} parcelName={parcelName} />
      <ZoneHealthPanel zones={data.zoneAssessments} isWholeParcel={data.isWholeParcel} />
      <PhenologyTimeline status={data.phenologyStatus} />
      <CropHealthRisksPanel diseases={data.diseases} assessment={data.assessment} />
      <CropHealthDetailTabs
        parcelId={parcelId}
        assessment={data.assessment}
        phenology={data.phenologyParams}
        trend={data.trend}
        correlation={data.correlation}
        correlationStats={data.correlationStats}
      />

      <div className="mt-3 border border-nkz-border rounded-lg overflow-hidden bg-nkz-surface-raised">
        <button
          type="button"
          className="w-full flex items-center justify-between px-3 py-2 text-left bg-transparent border-none cursor-pointer"
          onClick={() => setShowDiagnostics((v) => !v)}
        >
          <span className="text-xs font-semibold uppercase tracking-wide text-nkz-text-secondary">
            {t('workbench.diagnosticsTitle')}
          </span>
          <span className="text-xs text-nkz-text-muted">{showDiagnostics ? '▾' : '▸'}</span>
        </button>
        {showDiagnostics && (
          <div className="border-t border-nkz-border px-1 pb-2">
            <SourceStatusPanel parcelId={parcelId} parcelName={parcelName} embedded />
          </div>
        )}
      </div>
    </div>
  );
};

export default ParcelHealthWorkbench;
