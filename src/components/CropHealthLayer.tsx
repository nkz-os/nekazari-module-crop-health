import React, { useEffect, useRef } from 'react';

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
    const viewerRef = useRef<any>(null);

    useEffect(() => {
        const sdk = (window as any).__NKZ_SDK__;
        if (!sdk?.useViewer) return;

        // Try to get viewer instance
        try {
            viewerRef.current = sdk.useViewer();
        } catch {
            // Not in a viewer context — skip rendering
            return;
        }

        const fetchAndRender = async () => {
            try {
                const resp = await fetch('/api/crop-health/assessments/all');
                if (!resp.ok) return;
                const { assessments } = await resp.json();
                if (!assessments?.length) return;

                const viewer = viewerRef.current;
                if (!viewer?.entities) return;

                // Remove existing crop-health entities
                viewer.entities.values.forEach((e: any) => {
                    if (e.id?.startsWith('crop-health-')) {
                        viewer.entities.remove(e);
                    }
                });

                // For each parcel with assessment data, try to get its entity from Cesium
                for (const a of assessments as ParcelAssessment[]) {
                    if (a.cwsiValue == null) continue;

                    // Find parcel entity in viewer
                    const parcelEntity = viewer.entities.values.find(
                        (e: any) => e.id?.includes(a.parcelId) || e.name?.includes(a.parcelId)
                    );
                    if (!parcelEntity?.polygon) continue;

                    const colors = CWSI_COLORS[a.overallSeverity] || CWSI_COLORS.LOW;
                    parcelEntity.polygon.material = (window as any).Cesium?.Color.fromCssColorString(
                        colors.fill
                    )?.withAlpha(colors.alpha);
                    parcelEntity.polygon.outline = true;
                    parcelEntity.polygon.outlineColor = (window as any).Cesium?.Color.fromCssColorString(
                        colors.fill
                    );

                    // Add label
                    if (!parcelEntity.label) {
                        parcelEntity.label = {
                            text: `${a.cwsiValue.toFixed(2)}`,
                            font: '12px sans-serif',
                            fillColor: (window as any).Cesium?.Color.WHITE,
                            outlineColor: (window as any).Cesium?.Color.BLACK,
                            outlineWidth: 2,
                            style: (window as any).Cesium?.LabelStyle.FILL_AND_OUTLINE,
                            verticalOrigin: (window as any).Cesium?.VerticalOrigin.BOTTOM,
                        };
                    }
                }
            } catch {
                // Silently fail — layer is non-critical
            }
        };

        fetchAndRender();
        const interval = setInterval(fetchAndRender, 5 * 60 * 1000);
        return () => clearInterval(interval);
    }, []);

    return null; // map-layer renders into Cesium, no DOM output
};

export default CropHealthLayer;
