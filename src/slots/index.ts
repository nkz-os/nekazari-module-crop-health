import CropHealthWidget from '../components/CropHealthWidget';
import CropHealthContextPanel from '../components/CropHealthContextPanel';
import CropHealthLayer from '../components/CropHealthLayer';
import DiseaseRiskWidget from '../components/DiseaseRiskWidget';
import DiseaseRiskContextPanel from '../components/DiseaseRiskContextPanel';
import CompactionRiskWidget from '../components/CompactionRiskWidget';

const MODULE_ID = 'crop-health';

export const moduleSlots = {
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
    {
      id: 'crop-health-compaction-risk',
      moduleId: MODULE_ID,
      component: 'CompactionRiskWidget',
      localComponent: CompactionRiskWidget,
      priority: 30,
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
};
