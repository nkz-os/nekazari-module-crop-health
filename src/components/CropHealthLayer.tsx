import React, { useEffect, useRef, useState } from 'react';
import { useViewer } from '@nekazari/sdk';
import { DAY_MS, latestAtOrBefore, snapToUtcDay } from '@nekazari/viewer-kit';
import { cropHealthFetch } from '../api/cropHealthApi';
import { MAP_LAYER_MODE_KEY, readMapLayerMode, type MapLayerMode } from '../constants';
import type { AssessmentData, ZoneAssessmentData } from '../types/assessment';
import {
  PARCEL_URN_PREFIX,
  fetchAssessmentHistory,
  parcelIdFromEntityId,
  toDailyPoints,
  type DailyPoint,
} from '../utils/assessmentHistory';

/** Wait for the cursor to settle: dragging the axis emits once per day crossed. */
const HISTORY_DEBOUNCE_MS = 250;
/** How far back from the cursor the latest assessment may be (the layer paints the last known state). */
const HISTORY_WINDOW_DAYS = 14;

const NO_DATA_COLOR = { fill: '#9ca3af', alpha: 0.2 };

const SEVERITY_COLORS: Record<string, { fill: string; alpha: number }> = {
  LOW: { fill: '#16a34a', alpha: 0.3 },
  MEDIUM: { fill: '#d97706', alpha: 0.4 },
  HIGH: { fill: '#ea580c', alpha: 0.5 },
  CRITICAL: { fill: '#dc2626', alpha: 0.55 },
};

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
  if (value == null) return NO_DATA_COLOR;
  if (mode === 'vigor') {
    if (value >= 70) return { fill: '#16a34a', alpha: 0.45 };
    if (value >= 40) return { fill: '#d97706', alpha: 0.45 };
    return { fill: '#dc2626', alpha: 0.5 };
  }
  if (value >= 0.6) return { fill: '#dc2626', alpha: 0.5 };
  if (value >= 0.3) return { fill: '#d97706', alpha: 0.45 };
  return { fill: '#16a34a', alpha: 0.35 };
}

/**
 * The parcel's latest assessment with the values it had on the cursor's day.
 * Vigor has no history, so it is cleared and that mode shows no data.
 */
function historicalAssessment(latest: AssessmentData, point: DailyPoint | null): AssessmentData {
  return {
    ...latest,
    compositeStressIndex: point?.composite ?? undefined,
    cwsiValue: point?.cwsi ?? undefined,
    overallSeverity: point?.severity ?? '',
    vigorIndex: undefined,
  };
}

function historicalColor(a: AssessmentData, mode: MapLayerMode): { fill: string; alpha: number } {
  // layerColor's severity branch never reports "no data"; an unknown severity must not read as healthy.
  if (mode === 'severity' && !a.overallSeverity) return NO_DATA_COLOR;
  return layerColor(a, mode);
}

/** The selected parcel painted for a past cursor. point: undefined = still loading, null = no assessment. */
interface HistoricalSelection {
  parcelId: string;
  point: DailyPoint | null | undefined;
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

interface ViewerPolygon {
  material?: unknown;
  outline?: unknown;
  outlineColor?: unknown;
}

interface ViewerEntity {
  id?: string;
  name?: string;
  polygon?: ViewerPolygon;
  label?: unknown;
}

interface ViewerEntityCollection {
  add: (e: unknown) => void;
  remove: (e: unknown) => void;
  values: ViewerEntity[];
}

/** What a parcel entity looked like before the layer painted a historical state on it. */
interface PaintSnapshot {
  material: unknown;
  outline: unknown;
  outlineColor: unknown;
  label: unknown;
}

const CropHealthLayer: React.FC = () => {
  const { cesiumViewer, currentDate, selectedEntityId, selectedEntityType } = useViewer();
  const [mode, setMode] = useState<MapLayerMode>(readMapLayerMode);

  // Cursor in the past + a parcel selected: that parcel is painted with its state on the cursor's day.
  // Today and yesterday count as "now", so the layer then behaves exactly as without a timeline.
  const cursorMs = currentDate ? snapToUtcDay(currentDate.getTime()) : Number.NaN;
  const isParcelSelected =
    Boolean(selectedEntityId?.startsWith(PARCEL_URN_PREFIX)) || Boolean(selectedEntityType?.endsWith('AgriParcel'));
  const isCursorInPast = snapToUtcDay(Date.now()) - cursorMs > DAY_MS;
  const historyParcelId = isCursorInPast && isParcelSelected && selectedEntityId ? parcelIdFromEntityId(selectedEntityId) : null;
  const historyCursor = historyParcelId ? cursorMs : null;

  // Read by the paint function, so the 5-minute refresh keeps the historical colour.
  const historicalRef = useRef<HistoricalSelection | null>(null);
  // Repaints from the last fetched assessments, without refetching them.
  const repaintRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === MAP_LAYER_MODE_KEY && event.newValue) {
        setMode(readMapLayerMode());
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  useEffect(() => {
    let viewerEntities: ViewerEntityCollection | null = null;
    try {
      // The SDK types cesiumViewer as unknown (it does not depend on cesium).
      const viewer = cesiumViewer as { entities?: ViewerEntityCollection } | null | undefined;
      if (!viewer?.entities) return;
      viewerEntities = viewer.entities;
    } catch {
      return;
    }

    const clearCropHealthEntities = () => {
      // `values` is a live array: removing while iterating it skips elements, and the entities left
      // behind make the next `add` of the same id throw. Iterate over a copy.
      viewerEntities!.values.slice().forEach((e: { id?: string }) => {
        if (e.id?.startsWith('crop-health-')) {
          viewerEntities!.remove(e);
        }
      });
    };

    // Parcel entities belong to the host and the layer paints them in place. A historical colour must
    // never outlive its date, so each one is snapshotted before it is painted and put back before the
    // next paint (which then repaints the current state as usual) and when the layer goes away.
    const snapshots = new Map<ViewerEntity, PaintSnapshot>();
    const restoreSnapshots = () => {
      snapshots.forEach((snapshot, entity) => {
        if (entity.polygon) {
          entity.polygon.material = snapshot.material;
          entity.polygon.outline = snapshot.outline;
          entity.polygon.outlineColor = snapshot.outlineColor;
        }
        entity.label = snapshot.label;
      });
      snapshots.clear();
    };

    // Last fetched data, so a change of the historical colour repaints without refetching.
    let cache: { assessments: AssessmentData[]; zones: ZoneAssessmentData[] } | null = null;

    const fetchAndRender = async (fromCache = false) => {
      const currentMode = readMapLayerMode();
      setMode(currentMode);

      // 'off' = user turned the layer off — clear everything and stop rendering
      // so the crop-health overlay never blocks the parcel or other layers.
      if (currentMode === 'off') {
        clearCropHealthEntities();
        restoreSnapshots();
        return;
      }

      if (!fromCache || !cache) {
        const [parcelData, zoneData] = await Promise.all([
          cropHealthFetch<{ assessments: AssessmentData[] }>('/assessments/all'),
          cropHealthFetch<{ zones: ZoneAssessmentData[] }>('/assessments/zones/all'),
        ]);
        cache = { assessments: parcelData?.assessments ?? [], zones: zoneData?.zones ?? [] };
      }

      const { assessments, zones } = cache;

      restoreSnapshots();
      clearCropHealthEntities();
      if (!assessments.length && !zones.length) return;

      const Cesium = (window as { Cesium?: typeof import('cesium') }).Cesium;
      if (!Cesium) return;

      const zonedParcels = new Set(zones.map((z) => z.parcelId).filter(Boolean) as string[]);

      // Zones have no history: while the cursor is in the past the selected parcel is painted whole instead.
      const historicalParcelId = historicalRef.current?.parcelId;

      for (const zone of zones) {
        if (!zone.geometry || !zone.parcelId || !zone.zoneId) continue;
        if (zone.parcelId === historicalParcelId) continue;
        if (currentMode !== 'severity' && layerValue(zone, currentMode) == null) continue;

        const colors = layerColor(zone, currentMode);
        const material = Cesium.Color.fromCssColorString(colors.fill)?.withAlpha(colors.alpha);
        const outline = Cesium.Color.fromCssColorString(colors.fill);
        const rings = polygonRings(zone.geometry);

        for (let i = 0; i < rings.length; i += 1) {
          const positions = Cesium.Cartesian3.fromDegreesArray(ringToDegreesArray(rings[i]));
          viewerEntities!.add({
            id: `crop-health-zone-${zone.parcelId}-${zone.zoneId}-${i}`,
            polygon: {
              hierarchy: positions,
              material,
              outline: true,
              outlineColor: outline,
              // No height: the polygon drapes on terrain (a height of 0 buries
              // it under real terrain — IDENA/IGN elevations in the viewer).
              classificationType: Cesium.ClassificationType.TERRAIN,
            },
          });
        }

        const centroid = zoneCentroid(zone.geometry);
        if (centroid) {
          viewerEntities!.add({
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
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
          });
        }
      }

      for (const a of assessments) {
        if (!a.parcelId) continue;
        const historical = historicalRef.current?.parcelId === a.parcelId ? historicalRef.current : null;
        if (zonedParcels.has(a.parcelId) && !historical) continue;
        // History still loading: leave the parcel as it is rather than paint today's state for a past date.
        if (historical && historical.point === undefined) continue;
        const shown = historical ? historicalAssessment(a, historical.point ?? null) : a;
        if (!historical && currentMode !== 'severity' && layerValue(a, currentMode) == null) continue;

        const parcelEntity = viewerEntities!.values.find(
          (e: { id?: string; name?: string }) =>
            e.id?.includes(a.parcelId || '') || e.name?.includes(a.parcelId || ''),
        );
        if (!parcelEntity?.polygon) continue;

        if (historical && !snapshots.has(parcelEntity)) {
          snapshots.set(parcelEntity, {
            material: parcelEntity.polygon.material,
            outline: parcelEntity.polygon.outline,
            outlineColor: parcelEntity.polygon.outlineColor,
            label: parcelEntity.label,
          });
        }

        const colors = historical ? historicalColor(shown, currentMode) : layerColor(a, currentMode);
        parcelEntity.polygon.material = Cesium.Color.fromCssColorString(colors.fill)?.withAlpha(colors.alpha);
        parcelEntity.polygon.outline = true;
        parcelEntity.polygon.outlineColor = Cesium.Color.fromCssColorString(colors.fill);

        parcelEntity.label = {
          text: layerLabel(shown, currentMode),
          font: '12px sans-serif',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        };
      }
    };

    fetchAndRender();
    repaintRef.current = () => {
      if (cache) void fetchAndRender(true);
    };
    const interval = setInterval(fetchAndRender, 5 * 60 * 1000);
    return () => {
      clearInterval(interval);
      repaintRef.current = null;
      clearCropHealthEntities();
      restoreSnapshots();
    };
  }, [cesiumViewer, mode]);

  // History of the selected parcel on the cursor's day. Debounced: dragging the axis moves the cursor
  // once per day crossed, and only the position it settles on is worth a request.
  useEffect(() => {
    if (!historyParcelId || historyCursor == null) {
      if (historicalRef.current) {
        historicalRef.current = null;
        repaintRef.current?.();
      }
      return undefined;
    }

    historicalRef.current = { parcelId: historyParcelId, point: undefined };
    let cancelled = false;
    const timer = setTimeout(() => {
      void fetchAssessmentHistory(historyParcelId, historyCursor - HISTORY_WINDOW_DAYS * DAY_MS, historyCursor).then(
        (points) => {
          if (cancelled) return;
          const point = latestAtOrBefore(toDailyPoints(points), (p) => p.time, historyCursor);
          historicalRef.current = { parcelId: historyParcelId, point };
          repaintRef.current?.();
        },
      );
    }, HISTORY_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [historyParcelId, historyCursor]);

  return null;
};

export default CropHealthLayer;
