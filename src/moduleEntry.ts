import CropHealthWidget from './components/CropHealthWidget';
import CropHealthContextPanel from './components/CropHealthContextPanel';
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
    },
};

(window as any).__NKZ_MODULE_CROP_HEALTH__ = moduleExport;
export default moduleExport;
