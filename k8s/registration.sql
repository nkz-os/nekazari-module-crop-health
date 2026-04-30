-- =============================================================================
-- Crop Health Engine — Marketplace Registration
-- =============================================================================
-- Run once per environment to register this module in marketplace_modules.
-- This is a headless backend module — no frontend IIFE bundle.
-- =============================================================================

INSERT INTO marketplace_modules (
    id,
    name,
    display_name,
    description,
    remote_entry_url,
    version,
    author,
    category,
    route_path,
    label,
    module_type,
    required_plan_type,
    pricing_tier,
    is_local,
    is_active,
    required_roles,
    metadata
) VALUES (
    'crop-health',
    'crop-health',
    'Crop Health Engine',
    'Real-time biophysical inference engine: CWSI, MDS, water balance from sensor data',
    NULL,  -- No frontend IIFE — headless backend module
    '1.0.0',
    'k8-benetis',
    'analytics',
    NULL,  -- No route — no frontend
    'Crop Health Engine',
    'ADDON_FREE',
    'basic',
    'FREE',
    false,
    true,
    ARRAY['Farmer', 'TenantAdmin', 'PlatformAdmin'],
    '{"icon": "🌱", "color": "#16A34A", "headless": true}'::jsonb
) ON CONFLICT (id) DO UPDATE SET
    display_name   = EXCLUDED.display_name,
    description    = EXCLUDED.description,
    is_active      = true,
    updated_at     = NOW();
