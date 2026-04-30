import CropHealthWidget from './components/CropHealthWidget';
import CropHealthContextPanel from './components/CropHealthContextPanel';
import CropHealthLayer from './components/CropHealthLayer';
import './i18n';

const moduleExport = {
    id: 'crop-health',
    slots: {
        'dashboard-widget': {
            CropHealthWidget,
        },
        'context-panel': {
            CropHealthContextPanel,
        },
        'map-layer': {
            CropHealthLayer,
        },
    },
};

(window as any).__NKZ_MODULE_CROP_HEALTH__ = moduleExport;
export default moduleExport;
