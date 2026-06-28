import React, { useEffect } from 'react';
import { useViewer } from '@nekazari/sdk';
import { cropHealthFetch } from '../api/cropHealthApi';

interface ParcelAssessment {
  parcelId: string;
  cwsiValue?: number;
  overallSeverity: string;
}

const CWSI_COLORS: Record<string, { fill: string; alpha: number }> = {
  LOW: { fill: '#16a34a', alpha: 0.3 },
  MEDIUM: { fill: '#d97706', alpha: 0.4 },
  HIGH: { fill: '#ea580c', alpha: 0.5 },
  CRITICAL: { fill: '#dc2626', alpha: 0.55 },
};

const CropHealthLayer: React.FC = () => {
  const { cesiumViewer } = useViewer();

  useEffect(() => {
    if (!cesiumViewer?.entities) return;

    const fetchAndRender = async () => {
      const data = await cropHealthFetch<{ assessments: ParcelAssessment[] }>('/assessments/all');
      const assessments = data?.assessments ?? [];
      if (!assessments.length) return;

      cesiumViewer.entities.values.forEach((e: { id?: string }) => {
        if (e.id?.startsWith('crop-health-')) {
          cesiumViewer.entities.remove(e);
        }
      });

      for (const a of assessments) {
        if (a.cwsiValue == null) continue;

        const parcelEntity = cesiumViewer.entities.values.find(
          (e: { id?: string; name?: string }) =>
            e.id?.includes(a.parcelId) || e.name?.includes(a.parcelId),
        );
        if (!parcelEntity?.polygon) continue;

        const colors = CWSI_COLORS[a.overallSeverity] || CWSI_COLORS.LOW;
        const Cesium = (window as { Cesium?: typeof import('cesium') }).Cesium;
        if (!Cesium) continue;

        parcelEntity.polygon.material = Cesium.Color.fromCssColorString(colors.fill)?.withAlpha(colors.alpha);
        parcelEntity.polygon.outline = true;
        parcelEntity.polygon.outlineColor = Cesium.Color.fromCssColorString(colors.fill);

        if (!parcelEntity.label) {
          parcelEntity.label = {
            text: `${a.cwsiValue.toFixed(2)}`,
            font: '12px sans-serif',
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          };
        }
      }
    };

    fetchAndRender();
    const interval = setInterval(fetchAndRender, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [cesiumViewer]);

  return null;
};

export default CropHealthLayer;
