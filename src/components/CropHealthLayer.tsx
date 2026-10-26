import React, { useEffect, useRef, useState } from 'react';
import { useTranslation, useViewer } from '@nekazari/sdk';
import { DAY_MS, latestAtOrBefore, snapToUtcDay } from '@nekazari/viewer-kit';
import { cropHealthFetch } from '../api/cropHealthApi';
import { MAP_LAYER_MODE_KEY, readMapLayerMode, type MapLayerMode } from '../constants';
import type { AssessmentData, ZoneAssessmentData } from '../types/assessment';
import {
  SEVERITY_COLORS, emphasisStyle, parcelOnlyLabel, polygonRings, readZoneFromLocation, zoneCentroid, zoneEmphasis,
  zoneFillAlpha, zoneKey, zoneLabelStyle, zoneLabelText, zoneMapLabel, zoneNumbers, zoneSelection, type ZoneRef,
} from '../utils/zones';
import {
  fetchAssessmentHistory,
  parcelIdFromEntityId,
  toDailyPoints,
  type DailyPoint,
} from '../utils/assessmentHistory';

/** Wait for the cursor to settle: dragging the axis emits once per day crossed. */
const HISTORY_DEBOUNCE_MS = 250;
/** How far back from the cursor the latest assessment may be (the layer paints the last known state). */
const HISTORY_WINDOW_DAYS = 14;

/**
 * The entity types the timeline track is shown for (`showWhen` in slots/index.ts). The past is only
 * painted while that track is on screen: it is the axis that explains why the parcel looks as it does.
 */
const TIMELINE_PARCEL_TYPES: readonly string[] = ['AgriParcel', 'https://saref.etsi.org/saref4agri/AgriParcel'];

const NO_DATA_COLOR = { fill: '#9ca3af', alpha: 0.2 };

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

export function layerColor(a: AssessmentData, mode: MapLayerMode): { fill: string; alpha: number } {
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
  // CWSI is 0-1; the composite index is 0-100 (engines/composite.py).
  const [high, mid] = mode === 'composite' ? [60, 30] : [0.6, 0.3];
  if (value >= high) return { fill: '#dc2626', alpha: 0.5 };
  if (value >= mid) return { fill: '#d97706', alpha: 0.45 };
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
  const { t } = useTranslation('crop-health');
  const tRef = useRef(t);
  tRef.current = t;
  const { cesiumViewer, currentDate, selectedEntityId, selectedEntityType } = useViewer();
  const [mode, setMode] = useState<MapLayerMode>(readMapLayerMode);

  // Cursor in the past + a parcel selected: that parcel is painted with its state on the cursor's day.
  // Today and yesterday count as "now", so the layer then behaves exactly as without a timeline.
  // The selection must carry one of the track's entity types: the host's default cursor is in the past,
  // and a selection without a type (a deep link) shows no track, so nothing would explain the old colour.
  const cursorMs = currentDate ? snapToUtcDay(currentDate.getTime()) : Number.NaN;
  const isParcelSelected = Boolean(selectedEntityType && TIMELINE_PARCEL_TYPES.includes(selectedEntityType));
  const isCursorInPast = snapToUtcDay(Date.now()) - cursorMs > DAY_MS;
  const historyParcelId = isCursorInPast && isParcelSelected && selectedEntityId ? parcelIdFromEntityId(selectedEntityId) : null;
  const historyCursor = historyParcelId ? cursorMs : null;

  // Read by the paint function, so the 5-minute refresh keeps the historical colour.
  const historicalRef = useRef<HistoricalSelection | null>(null);
  // Repaints from the last fetched assessments, without refetching them.
  const repaintRef = useRef<(() => void) | null>(null);
  // Zones of the last fetch, and the pinned zone the camera still has to fly to (once per pin).
  const zonesRef = useRef<ZoneAssessmentData[]>([]);
  const pendingFlyRef = useRef<ZoneRef | null>(null);
  const flyToPinnedRef = useRef<(() => void) | null>(null);

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
    // Set when this effect is torn down (mode change, unmount). A fetch still in flight must then paint
    // nothing: it would write into entities whose snapshots belong to a map nobody restores any more.
    let disposed = false;

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
        if (disposed) return;
        cache = { assessments: parcelData?.assessments ?? [], zones: zoneData?.zones ?? [] };
      }

      const { assessments, zones } = cache;
      zonesRef.current = zones;
      flyToPinnedRef.current?.();

      restoreSnapshots();
      clearCropHealthEntities();
      if (!assessments.length && !zones.length) return;

      const Cesium = (window as { Cesium?: typeof import('cesium') }).Cesium;
      if (!Cesium) return;

      // A parcel whose zones all equal the parcel value is painted whole, with no zone entities.
      const zonesByParcel = new Map<string, ZoneAssessmentData[]>();
      for (const z of zones) {
        if (!z.parcelId) continue;
        zonesByParcel.set(z.parcelId, [...(zonesByParcel.get(z.parcelId) ?? []), z]);
      }
      const wholeParcels = new Set<string>();
      const zonedParcels = new Set<string>();
      zonesByParcel.forEach((list, parcelId) => (parcelOnlyLabel(list) ? wholeParcels : zonedParcels).add(parcelId));

      // Zones have no history: while the cursor is in the past the selected parcel is painted whole instead.
      const historicalParcelId = historicalRef.current?.parcelId;

      // Numbered over every zone of a parcel, as the side panel does, so both show the same numbers.
      const numbers = zoneNumbers(zones);
      const selection = zoneSelection.get();

      for (const zone of zones) {
        if (!zone.geometry || !zone.parcelId || !zone.zoneId) continue;
        if (zone.parcelId === historicalParcelId) continue;
        if (wholeParcels.has(zone.parcelId)) continue;
        if (currentMode !== 'severity' && layerValue(zone, currentMode) == null) continue;

        const colors = layerColor(zone, currentMode);
        const emphasis = zoneEmphasis(selection, zone.parcelId, zone.zoneId);
        const style = emphasisStyle(emphasis, zoneFillAlpha(zone, colors.alpha));
        const number = numbers.get(zoneKey(zone.parcelId, zone.zoneId));
        const description = zoneMapLabel(number, layerLabel(zone, currentMode));
        const labelStyle = zoneLabelStyle(emphasis);
        const material = Cesium.Color.fromCssColorString(colors.fill)?.withAlpha(style.fillAlpha);
        const outline = (style.outlineWhite ? Cesium.Color.WHITE : Cesium.Color.fromCssColorString(colors.fill))
          ?.withAlpha(style.outlineAlpha);
        const rings = polygonRings(zone.geometry);

        for (let i = 0; i < rings.length; i += 1) {
          const positions = Cesium.Cartesian3.fromDegreesArray(ringToDegreesArray(rings[i]));
          viewerEntities!.add({
            id: `crop-health-zone-${zone.parcelId}-${zone.zoneId}-${i}`,
            description,
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
            description,
            position: Cesium.Cartesian3.fromDegrees(centroid[0], centroid[1]),
            label: {
              text: zoneLabelText(number),
              font: labelStyle.font,
              scaleByDistance: new Cesium.NearFarScalar(...labelStyle.scaleByDistance),
              fillColor: Cesium.Color.WHITE.withAlpha(style.labelAlpha),
              outlineColor: Cesium.Color.BLACK.withAlpha(style.labelAlpha),
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
          text: wholeParcels.has(a.parcelId) && !historical ? tRef.current('zones.parcelOnly') : layerLabel(shown, currentMode),
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
      disposed = true;
      clearInterval(interval);
      repaintRef.current = null;
      clearCropHealthEntities();
      restoreSnapshots();
    };
  }, [cesiumViewer, mode]);

  // Fly to the pinned zone once per pin. Pending until its zone is loaded (a deep link pins before the fetch ends).
  useEffect(() => {
    flyToPinnedRef.current = () => {
      const target = pendingFlyRef.current;
      const Cesium = (window as { Cesium?: typeof import('cesium') }).Cesium;
      const viewer = cesiumViewer as { camera?: { flyTo: (o: unknown) => void } } | null | undefined;
      if (!target || !Cesium || !viewer?.camera) return;
      const zone = zonesRef.current.find((z: ZoneAssessmentData) => z.parcelId === target.parcelId && z.zoneId === target.zoneId);
      const rings = polygonRings(zone?.geometry);
      if (!rings.length) return;
      pendingFlyRef.current = null;
      const positions = rings.flatMap((ring) => Cesium.Cartesian3.fromDegreesArray(ringToDegreesArray(ring)));
      viewer.camera.flyTo({ destination: Cesium.Rectangle.fromCartesianArray(positions), duration: 1.0 });
    };
    return () => {
      flyToPinnedRef.current = null;
    };
  }, [cesiumViewer]);

  // The zone pointed at in the side panel: repaint from the last data, without refetching. Hovering only
  // repaints; the camera moves when a zone is pinned (the panel's "show on map", or a deep link).
  useEffect(() => {
    let lastPinned = zoneSelection.getPinned();
    const unsubscribe = zoneSelection.subscribe(() => {
      const pinned = zoneSelection.getPinned();
      if (pinned !== lastPinned) {
        lastPinned = pinned;
        pendingFlyRef.current = pinned;
        flyToPinnedRef.current?.();
      }
      repaintRef.current?.();
    });
    // Deep link `?parcel=&zone=`: pin it unless it already is (a remount must not toggle it off).
    const ref = readZoneFromLocation(window.location.search);
    const current = zoneSelection.getPinned();
    if (ref && !(current && current.parcelId === ref.parcelId && current.zoneId === ref.zoneId)) zoneSelection.pin(ref);
    return unsubscribe;
  }, []);

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
