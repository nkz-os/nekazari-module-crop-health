import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import ParcelHealthWorkbench from './ParcelHealthWorkbench';

interface Props {
  parcelId?: string;
  parcelName?: string;
  entityData?: any;
}

function resolveParcelId(entityData: any): string | null {
  if (!entityData) return null;
  if (entityData.type === 'AgriParcel' || entityData.type?.endsWith('AgriParcel')) {
    return entityData.id?.replace('urn:ngsi-ld:AgriParcel:', '') || entityData.id;
  }
  if (entityData.type === 'AgriCrop' || entityData.type?.endsWith('AgriCrop')) {
    const ref = entityData.hasAgriParcel?.object
      || entityData.refAgriParcel?.object
      || entityData.hasAgriParcel
      || entityData.refAgriParcel;
    return ref?.replace?.('urn:ngsi-ld:AgriParcel:', '') || ref || null;
  }
  return null;
}

const CropHealthContextPanel: React.FC<Props> = ({
  parcelId: propParcelId,
  parcelName: propParcelName,
  entityData,
}) => {
  const { t } = useTranslation('crop-health');
  const effectiveParcelId = propParcelId || resolveParcelId(entityData);
  const effectiveParcelName = propParcelName || entityData?.name?.value || entityData?.name || '';

  if (!effectiveParcelId) {
    return (
      <div className="text-center p-4">
        <span className="text-2xl">🌱</span>
        <p className="text-sm text-nkz-text-muted mt-1">{t('contextPanel.noData')}</p>
      </div>
    );
  }

  return (
    <ParcelHealthWorkbench parcelId={effectiveParcelId} parcelName={effectiveParcelName} />
  );
};

export default CropHealthContextPanel;
