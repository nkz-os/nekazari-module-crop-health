import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Sprout } from 'lucide-react';
import { SlotShell } from '@nekazari/viewer-kit';
import { CROP_HEALTH_ACCENT } from '../constants';
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

  return (
    <SlotShell moduleId="crop-health" title={t('title')} icon={<Sprout className="w-4 h-4" />} accent={CROP_HEALTH_ACCENT}>
      {!effectiveParcelId ? (
        <div className="text-center p-4">
          <span className="text-2xl">🌱</span>
          <p className="text-sm text-nkz-text-muted mt-1">{t('contextPanel.noData')}</p>
        </div>
      ) : (
        <ParcelHealthWorkbench parcelId={effectiveParcelId} parcelName={effectiveParcelName} />
      )}
    </SlotShell>
  );
};

export default CropHealthContextPanel;
