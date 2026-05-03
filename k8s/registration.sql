-- =============================================================================
-- Crop Health Engine — Marketplace Registration
-- =============================================================================
-- Run once per environment to register this module in marketplace_modules.
-- This module has a frontend IIFE bundle with dashboard widgets and viewer slots.
-- =============================================================================

INSERT INTO marketplace_modules (
    id, name, display_name, description, remote_entry_url,
    version, author, category, route_path, label,
    module_type, required_plan_type, pricing_tier,
    is_local, is_active, required_roles, metadata
) VALUES (
    'crop-health',
    'crop-health',
    'Crop Health Engine',
    'Real-time crop health monitoring: CWSI (IR canopy), MDS (dendrometer), '
    'water balance, thermal stress, crop vigor, composite stress (Ky FAO-33), '
    'yield gap, WUE, and disease risk models (Mills, Magarey, TomCast, Gubler). '
    'Publishes CropHealthAssessment entities with data fidelity tracing.',
    '/modules/crop-health/nkz-module.js',
    '1.0.0',
    'nkz-os',
    'analytics',
    '/crop-health',
    'Crop Health',
    'ADDON_FREE',
    'basic',
    'FREE',
    false,
    true,
    ARRAY['Farmer', 'TenantAdmin', 'PlatformAdmin'],
    '{
        "icon": "🌱",
        "color": "#16A34A",
        "features": [
            "9 real-time biophysical engines",
            "5 epidemiological disease models",
            "dataFidelity tracing per assessment",
            "Dashboard widget + 3D viewer panel + heatmap layer",
            "CSV export with source metadata",
            "6 locales (es, en, ca, eu, fr, pt)"
        ]
    }'::jsonb
) ON CONFLICT (id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    remote_entry_url = EXCLUDED.remote_entry_url,
    route_path = EXCLUDED.route_path,
    is_active = true,
    updated_at = NOW();
