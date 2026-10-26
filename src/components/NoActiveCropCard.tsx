import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { navigateTo } from '../api/cropHealthApi';
import type { PlannedCrop } from '../types/assessment';

interface NoActiveCropCardProps {
  parcelId: string;
  plannedCrop: PlannedCrop | null;
  lastAssessment: { assessedAt: string; cropName?: string } | null;
}

const NoActiveCropCard: React.FC<NoActiveCropCardProps> = ({ parcelId, plannedCrop, lastAssessment }) => {
  const { t, i18n } = useTranslation('crop-health');
  const lang = i18n?.language || 'es';
  const plannedName = plannedCrop ? (plannedCrop.names?.[lang] ?? plannedCrop.species) : '';

  return (
    <div className="bg-nkz-surface-raised border border-nkz-border rounded-lg p-3 mb-3 space-y-2">
      <p className="text-lg font-semibold text-nkz-text-primary">{t('noCrop.title')}</p>
      {plannedCrop && (
        <p className="text-sm text-nkz-text-secondary">{t('noCrop.next', { crop: plannedName })}</p>
      )}
      <button
        type="button"
        className="text-sm text-nkz-accent-base underline bg-transparent cursor-pointer p-0"
        onClick={() => navigateTo(`/bioorchestrator?parcel=${encodeURIComponent(parcelId)}`)}
      >
        {t('noCrop.plan')}
      </button>
      {lastAssessment && (
        <p className="text-xs text-nkz-text-muted">
          {t('noCrop.last', {
            date: new Date(lastAssessment.assessedAt).toLocaleString(lang),
            crop: lastAssessment.cropName ?? '',
          })}
        </p>
      )}
    </div>
  );
};

export default NoActiveCropCard;
