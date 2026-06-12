import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import SourceStatusPanel from './SourceStatusPanel';
import CropStatusSnapshot from './CropStatusSnapshot';
import CropHealthDetail from './CropHealthDetail';

interface Props {
  parcelId?: string;
  parcelName?: string;
  entityData?: any;
  onOpenPhenology?: (species: string) => void;
}

/** Extract parcel ID from entity data, supporting both AgriParcel and AgriCrop types.
 *  Uses hasAgriParcel (FIWARE standard) with fallback refAgriParcel for migration. */
function resolveParcelId(entityData: any): string | null {
  if (!entityData) return null;
  // If directly an AgriParcel, its ID is the parcel
  if (entityData.type === 'AgriParcel' || entityData.type?.endsWith('AgriParcel')) {
    return entityData.id?.replace('urn:ngsi-ld:AgriParcel:', '') || entityData.id;
  }
  // If an AgriCrop, resolve parent via hasAgriParcel (FIWARE standard)
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

  // Resolve parcelId: priority to direct prop, then from entityData
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
    <div>
      <SourceStatusPanel parcelId={effectiveParcelId} parcelName={effectiveParcelName} />
      <CropStatusSnapshot parcelId={effectiveParcelId} parcelName={effectiveParcelName} />
      <CropHealthDetail parcelId={effectiveParcelId} />
    </div>
  );
};

export default CropHealthContextPanel;
