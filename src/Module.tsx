import { defineModule } from '@nekazari/module-kit';
import { lazy } from 'react';
import './i18n';
import { moduleSlots } from './slots';
import pkg from '../package.json';

const MainPage = lazy(() => import('./App'));

export default defineModule({
  id: 'crop-health',
  displayName: 'Crop Health',
  version: pkg.version,
  hostApiVersion: '^2.0.0',
  description: 'Crop water stress, disease risk and yield gap insights — Nekazari Platform Module',
  accent: { base: '#16A34A', soft: '#DCFCE7', strong: '#15803D' },
  icon: 'sprout',
  main: MainPage,
  slots: moduleSlots as never,
});
