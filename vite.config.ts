import { defineConfig } from 'vite';
import { nkzModulePreset } from '@nekazari/module-builder';

export default defineConfig(nkzModulePreset({
    moduleId: 'crop-health',
    entry: 'src/moduleEntry.ts',
}));
