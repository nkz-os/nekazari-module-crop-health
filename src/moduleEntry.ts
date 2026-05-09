/**
 * IIFE entry point — called when the host injects this bundle via <script>.
 * Must call window.__NKZ__.register() to activate the module.
 */
import CropHealthWidget from './components/CropHealthWidget';
import CropHealthContextPanel from './components/CropHealthContextPanel';
import CropHealthLayer from './components/CropHealthLayer';
import DiseaseRiskWidget from './components/DiseaseRiskWidget';
import DiseaseRiskContextPanel from './components/DiseaseRiskContextPanel';
import pkg from '../package.json';
import './i18n';

const MODULE_ID = 'crop-health';

if (typeof window !== 'undefined' && window.__NKZ__) {
  window.__NKZ__.register({
    id: MODULE_ID,
    version: pkg.version,
    viewerSlots: {
      'dashboard-widget': [
        {
          id: 'crop-health-widget',
          moduleId: MODULE_ID,
          component: 'CropHealthWidget',
          localComponent: CropHealthWidget,
          priority: 10,
        },
        {
          id: 'crop-health-disease-risk',
          moduleId: MODULE_ID,
          component: 'DiseaseRiskWidget',
          localComponent: DiseaseRiskWidget,
          priority: 20,
        },
      ],
      'context-panel': [
        {
          id: 'crop-health-context',
          moduleId: MODULE_ID,
          component: 'CropHealthContextPanel',
          localComponent: CropHealthContextPanel,
          priority: 10,
        },
        {
          id: 'crop-health-disease-context',
          moduleId: MODULE_ID,
          component: 'DiseaseRiskContextPanel',
          localComponent: DiseaseRiskContextPanel,
          priority: 20,
        },
      ],
      'map-layer': [
        {
          id: 'crop-health-layer',
          moduleId: MODULE_ID,
          component: 'CropHealthLayer',
          localComponent: CropHealthLayer,
          priority: 10,
        },
      ],
    },
  });
}
