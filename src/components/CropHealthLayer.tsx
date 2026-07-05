import React, { useEffect, useState } from 'react';
import { useViewer } from '@nekazari/sdk';
import { cropHealthFetch } from '../api/cropHealthApi';
import { MAP_LAYER_MODE_KEY, type MapLayerMode } from '../constants';
import type { AssessmentData } from '../types/assessment';

const SEVERITY_COLORS: Record<string, { fill: string; alpha: number }> = {
  LOW: { fill: '#16a34a', alpha: 0.3 },
  MEDIUM: { fill: '#d97706', alpha: 0.4 },
  HIGH: { fill: '#ea580c', alpha: 0.5 },
  CRITICAL: { fill: '#dc2626', alpha: 0.55 },
};

function readMapMode(): MapLayerMode {
  if (typeof window === 'undefined') return 'severity';
  const stored = window.localStorage.getItem(MAP_LAYER_MODE_KEY);
  if (stored === 'cwsi' || stored === 'composite' || stored === 'vigor' || stored === 'severity') {
    return stored;
  }
  return 'severity';
}

function layerValue(a: AssessmentData, mode: MapLayerMode): number | null {
  switch (mode) {
    case 'cwsi':
      return a.cwsiValue ?? null;
    case 'composite':
      return a.compositeStressIndex ?? null;
    case 'vigor':
      return a.vigorIndex != null ? a.vigorIndex * 100 : null;
    default:
      return null;
  }
}

function layerLabel(a: AssessmentData, mode: MapLayerMode): string {
  if (mode === 'severity') return a.overallSeverity?.[0] ?? '?';
  const value = layerValue(a, mode);
  return value != null ? value.toFixed(mode === 'vigor' ? 0 : 2) : '—';
}

function layerColor(a: AssessmentData, mode: MapLayerMode): { fill: string; alpha: number } {
  if (mode === 'severity') {
    return SEVERITY_COLORS[a.overallSeverity] || SEVERITY_COLORS.LOW;
  }
  const value = layerValue(a, mode);
  if (value == null) return { fill: '#9ca3af', alpha: 0.2 };
  if (mode === 'vigor') {
    if (value >= 70) return { fill: '#16a34a', alpha: 0.45 };
    if (value >= 40) return { fill: '#d97706', alpha: 0.45 };
    return { fill: '#dc2626', alpha: 0.5 };
  }
  if (value >= 0.6) return { fill: '#dc2626', alpha: 0.5 };
  if (value >= 0.3) return { fill: '#d97706', alpha: 0.45 };
  return { fill: '#16a34a', alpha: 0.35 };
}

const CropHealthLayer: React.FC = () => {
  const { cesiumViewer } = useViewer();
  const [mode, setMode] = useState<MapLayerMode>(readMapMode);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === MAP_LAYER_MODE_KEY && event.newValue) {
        setMode(readMapMode());
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  useEffect(() => {
    if (!cesiumViewer?.entities) return;

    const fetchAndRender = async () => {
      const currentMode = readMapMode();
      setMode(currentMode);
      const data = await cropHealthFetch<{ assessments: AssessmentData[] }>('/assessments/all');
      const assessments = data?.assessments ?? [];
      if (!assessments.length) return;

      cesiumViewer.entities.values.forEach((e: { id?: string }) => {
        if (e.id?.startsWith('crop-health-')) {
          cesiumViewer.entities.remove(e);
        }
      });

      const Cesium = (window as { Cesium?: typeof import('cesium') }).Cesium;
      if (!Cesium) return;

      for (const a of assessments) {
        if (currentMode !== 'severity' && layerValue(a, currentMode) == null) continue;

        const parcelEntity = cesiumViewer.entities.values.find(
          (e: { id?: string; name?: string }) =>
            e.id?.includes(a.parcelId || '') || e.name?.includes(a.parcelId || ''),
        );
        if (!parcelEntity?.polygon) continue;

        const colors = layerColor(a, currentMode);
        parcelEntity.polygon.material = Cesium.Color.fromCssColorString(colors.fill)?.withAlpha(colors.alpha);
        parcelEntity.polygon.outline = true;
        parcelEntity.polygon.outlineColor = Cesium.Color.fromCssColorString(colors.fill);

        parcelEntity.label = {
          text: layerLabel(a, currentMode),
          font: '12px sans-serif',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        };
      }
    };

    fetchAndRender();
    const interval = setInterval(fetchAndRender, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [cesiumViewer, mode]);

  return null;
};

export default CropHealthLayer;
