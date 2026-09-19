export const MODULE_ID = 'crop-health';

export const CROP_HEALTH_ACCENT = {
  base: '#16A34A',
  soft: '#DCFCE7',
  strong: '#15803D',
} as const;

export const MAP_LAYER_MODE_KEY = 'nkz-crop-health-map-mode';

export type MapLayerMode = 'cwsi' | 'composite' | 'vigor' | 'severity' | 'off';

export const MAP_LAYER_MODES: MapLayerMode[] = ['severity', 'cwsi', 'composite', 'vigor', 'off'];
