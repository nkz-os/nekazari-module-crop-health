import CropHealthWidget from '../components/CropHealthWidget';
import CropHealthContextPanel from '../components/CropHealthContextPanel';
import CropHealthLayer from '../components/CropHealthLayer';
import DiseaseRiskWidget from '../components/DiseaseRiskWidget';
import CompactionRiskWidget from '../components/CompactionRiskWidget';
import CropHealthMapModeWidget from '../components/CropHealthMapModeWidget';
import CropHealthLayerToggle from '../components/CropHealthLayerToggle';
import CropHealthTimelineTrack from '../components/CropHealthTimelineTrack';

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
    {
      id: 'crop-health-map-mode',
      moduleId: MODULE_ID,
      component: 'CropHealthMapModeWidget',
      localComponent: CropHealthMapModeWidget,
      priority: 40,
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
  ],
  'layer-toggle': [
    {
      id: 'crop-health-layer-toggle',
      moduleId: MODULE_ID,
      component: 'CropHealthLayerToggle',
      localComponent: CropHealthLayerToggle,
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
  'timeline-track': [
    {
      id: 'crop-health-timeline-track',
      moduleId: MODULE_ID,
      component: 'CropHealthTimelineTrack',
      localComponent: CropHealthTimelineTrack,
      priority: 20,
      showWhen: { entityType: ['AgriParcel', 'https://saref.etsi.org/saref4agri/AgriParcel'] },
    },
  ],
};
