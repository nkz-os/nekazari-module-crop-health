import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { SlotShellCompact } from '@nekazari/viewer-kit';
import { CROP_HEALTH_ACCENT, MAP_LAYER_MODE_KEY, MAP_LAYER_MODES, readMapLayerMode, type MapLayerMode } from '../constants';

/**
 * Layers-panel options for the crop-health map layer. Shares the mode with the
 * dashboard widget through the same storage key, and keeps no state of its own
 * so closing the panel changes nothing.
 */
const CropHealthLayerToggle: React.FC = () => {
  const { t } = useTranslation('crop-health');
  const [mode, setMode] = React.useState<MapLayerMode>(readMapLayerMode);

  React.useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === MAP_LAYER_MODE_KEY) setMode(readMapLayerMode());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const selectMode = (next: MapLayerMode) => {
    setMode(next);
    window.localStorage.setItem(MAP_LAYER_MODE_KEY, next);
    window.dispatchEvent(new StorageEvent('storage', { key: MAP_LAYER_MODE_KEY, newValue: next }));
  };

  return (
    <SlotShellCompact moduleId="crop-health" accent={CROP_HEALTH_ACCENT}>
      <div className="flex flex-wrap gap-1" role="group" aria-label={t('mapLayer.title')}>
        {MAP_LAYER_MODES.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={mode === item}
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
    </SlotShellCompact>
  );
};

export default CropHealthLayerToggle;
