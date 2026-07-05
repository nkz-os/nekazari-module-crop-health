import React, { useEffect, useState } from 'react';
import { useViewer } from '@nekazari/sdk';
import { cropHealthFetch } from '../api/cropHealthApi';
import { MAP_LAYER_MODE_KEY, type MapLayerMode } from '../constants';
import type { AssessmentData, ZoneAssessmentData } from '../types/assessment';

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

function ringToDegreesArray(ring: number[][]): number[] {
  const flat: number[] = [];
  for (const [lon, lat] of ring) {
    flat.push(lon, lat);
  }
  return flat;
}

function polygonRings(geometry: ZoneAssessmentData['geometry']): number[][][] {
  if (!geometry) return [];
  if (geometry.type === 'Polygon') {
    return geometry.coordinates as number[][][];
  }
  if (geometry.type === 'MultiPolygon') {
    return (geometry.coordinates as number[][][][]).map((poly) => poly[0]);
  }
  return [];
}

function zoneCentroid(geometry: ZoneAssessmentData['geometry']): [number, number] | null {
  const rings = polygonRings(geometry);
  const ring = rings[0];
  if (!ring?.length) return null;
  let lon = 0;
  let lat = 0;
  for (const [x, y] of ring) {
    lon += x;
    lat += y;
  }
  return [lon / ring.length, lat / ring.length];
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

    const clearCropHealthEntities = () => {
      cesiumViewer.entities.values.forEach((e: { id?: string }) => {
        if (e.id?.startsWith('crop-health-')) {
          cesiumViewer.entities.remove(e);
        }
      });
    };

    const fetchAndRender = async () => {
      const currentMode = readMapMode();
      setMode(currentMode);

      const [parcelData, zoneData] = await Promise.all([
        cropHealthFetch<{ assessments: AssessmentData[] }>('/assessments/all'),
        cropHealthFetch<{ zones: ZoneAssessmentData[] }>('/assessments/zones/all'),
      ]);

      const assessments = parcelData?.assessments ?? [];
      const zones = zoneData?.zones ?? [];

      clearCropHealthEntities();
      if (!assessments.length && !zones.length) return;

      const Cesium = (window as { Cesium?: typeof import('cesium') }).Cesium;
      if (!Cesium) return;

      const zonedParcels = new Set(zones.map((z) => z.parcelId).filter(Boolean) as string[]);

      for (const zone of zones) {
        if (!zone.geometry || !zone.parcelId || !zone.zoneId) continue;
        if (currentMode !== 'severity' && layerValue(zone, currentMode) == null) continue;

        const colors = layerColor(zone, currentMode);
        const material = Cesium.Color.fromCssColorString(colors.fill)?.withAlpha(colors.alpha);
        const outline = Cesium.Color.fromCssColorString(colors.fill);
        const rings = polygonRings(zone.geometry);

        for (let i = 0; i < rings.length; i += 1) {
          const positions = Cesium.Cartesian3.fromDegreesArray(ringToDegreesArray(rings[i]));
          cesiumViewer.entities.add({
            id: `crop-health-zone-${zone.parcelId}-${zone.zoneId}-${i}`,
            polygon: {
              hierarchy: positions,
              material,
              outline: true,
              outlineColor: outline,
              height: 0,
            },
          });
        }

        const centroid = zoneCentroid(zone.geometry);
        if (centroid) {
          cesiumViewer.entities.add({
            id: `crop-health-zone-label-${zone.parcelId}-${zone.zoneId}`,
            position: Cesium.Cartesian3.fromDegrees(centroid[0], centroid[1]),
            label: {
              text: layerLabel(zone, currentMode),
              font: '11px sans-serif',
              fillColor: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.CENTER,
              pixelOffset: new Cesium.Cartesian2(0, -8),
            },
          });
        }
      }

      for (const a of assessments) {
        if (!a.parcelId || zonedParcels.has(a.parcelId)) continue;
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
    return () => {
      clearInterval(interval);
      clearCropHealthEntities();
    };
  }, [cesiumViewer, mode]);

  return null;
};

export default CropHealthLayer;
