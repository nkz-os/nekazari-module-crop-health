const en = {
    'crop-health': {
        title: 'Crop Health',
        loading: 'Loading...',
        error: 'Error',
        noAssessments: 'No crop health assessments yet',
        noAssessmentsHint: 'Connect sensors to start monitoring crop stress',
        waterBalance: 'Water Balance',
        defaultParams: 'Default params',
        severity: {
            LOW: 'Healthy',
            MEDIUM: 'Monitor',
            HIGH: 'Stressed',
            CRITICAL: 'Critical',
        },
        thermal: 'Thermal',
        vigor: 'Vigor',
        action: {
            noAction: 'No action needed',
            monitor: 'Monitor closely',
            irrigateScheduled: 'Schedule irrigation',
            irrigateImmediate: 'IRRIGATE NOW',
        },
    },
};

const es = {
    'crop-health': {
        title: 'Salud del Cultivo',
        loading: 'Cargando...',
        error: 'Error',
        noAssessments: 'Sin evaluaciones de salud del cultivo',
        noAssessmentsHint: 'Conecta sensores para monitorizar el estrés del cultivo',
        waterBalance: 'Balance Hídrico',
        defaultParams: 'Parámetros genéricos',
        severity: {
            LOW: 'Saludable',
            MEDIUM: 'Vigilar',
            HIGH: 'Estresado',
            CRITICAL: 'Crítico',
        },
        thermal: 'Térmico',
        vigor: 'Vigor',
        action: {
            noAction: 'Sin acción necesaria',
            monitor: 'Monitorizar',
            irrigateScheduled: 'Programar riego',
            irrigateImmediate: 'REGAR AHORA',
        },
    },
};

// Register with NKZ i18n
const nkzSdk = (window as any).__NKZ_SDK__;
if (nkzSdk?.i18n) {
    nkzSdk.i18n.addResources('en', 'crop-health', en['crop-health']);
    nkzSdk.i18n.addResources('es', 'crop-health', es['crop-health']);
}

export { en, es };
