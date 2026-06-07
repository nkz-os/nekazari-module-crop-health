import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import SourceStatusPanel from './SourceStatusPanel';
import CropStatusSnapshot from './CropStatusSnapshot';
import CropHealthDetail from './CropHealthDetail';

interface Props {
  parcelId: string;
  parcelName?: string;
  onOpenPhenology?: (species: string) => void;
}

const CropHealthContextPanel: React.FC<Props> = ({ parcelId, parcelName }) => {
  const { t } = useTranslation('crop-health');

  if (!parcelId) {
    return (
      <div className="text-center p-4">
        <span className="text-2xl">🌱</span>
        <p className="text-nkz-text-muted text-sm mt-1">{t('contextPanel.noData')}</p>
      </div>
    );
  }

  return (
    <div>
      <SourceStatusPanel parcelId={parcelId} parcelName={parcelName} />
      <CropStatusSnapshot parcelId={parcelId} parcelName={parcelName} />
      <CropHealthDetail parcelId={parcelId} />
    </div>
  );
};

export default CropHealthContextPanel;
