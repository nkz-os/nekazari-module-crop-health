import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Layers } from 'lucide-react';
import { SlotShell } from '@nekazari/viewer-kit';
import { CROP_HEALTH_ACCENT, MAP_LAYER_MODE_KEY, MAP_LAYER_MODES, type MapLayerMode } from '../constants';

const CropHealthMapModeWidget: React.FC = () => {
  const { t } = useTranslation('crop-health');
  const [mode, setMode] = React.useState<MapLayerMode>(() => {
    if (typeof window === 'undefined') return 'severity';
    const stored = window.localStorage.getItem(MAP_LAYER_MODE_KEY);
    return MAP_LAYER_MODES.includes(stored as MapLayerMode) ? (stored as MapLayerMode) : 'severity';
  });

  const selectMode = (next: MapLayerMode) => {
    setMode(next);
    window.localStorage.setItem(MAP_LAYER_MODE_KEY, next);
    window.dispatchEvent(new StorageEvent('storage', { key: MAP_LAYER_MODE_KEY, newValue: next }));
  };

  return (
    <SlotShell moduleId="crop-health" title={t('mapLayer.title')} icon={<Layers className="w-4 h-4" />} accent={CROP_HEALTH_ACCENT}>
      <div className="flex flex-wrap gap-1">
        {MAP_LAYER_MODES.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => selectMode(item)}
            className={`px-2 py-1 rounded text-xs border cursor-pointer ${
              mode === item
                ? 'bg-nkz-accent-soft border-nkz-accent-base text-nkz-accent-strong'
                : 'bg-nkz-surface border-nkz-border text-nkz-text-secondary'
            }`}
          >
            {t(`mapLayer.${item}`)}
          </button>
        ))}
      </div>
    </SlotShell>
  );
};

export default CropHealthMapModeWidget;
