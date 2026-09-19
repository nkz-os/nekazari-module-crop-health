const API_BASE = '/api/crop-health';

// Cross-module BioOrchestrator reference data lives under /api/graph, which is
// only routed on the platform API host (Traefik routes it direct to the
// bioorchestrator backend). A relative '/api/graph/...' resolves against the
// frontend host and falls through to the api-gateway auto-proxy, which has no
// 'graph' module → 404. Use the same absolute base the bioorchestrator module
// itself uses (VITE_API_URL is the platform API host, no /api suffix).
const PLATFORM_API_BASE =
  (import.meta as any).env?.VITE_API_URL || 'https://nkz.robotika.cloud';

// Auth helper — reads the JWT the host injects as `window.keycloak` (same
// pattern the bioorchestrator module uses). Cross-module /api/graph calls go
// DIRECT to bioorchestrator (no api-gateway in front), so the tenant can only
// be resolved from the Bearer token — cookies/headers are not forwarded there.
function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const keycloak = (window as any).keycloak;
    if (keycloak?.token) return keycloak.token;
  } catch { /* keycloak not available */ }
  return null;
}

export function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function cropHealthFetch<T>(path: string): Promise<T | null> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, { credentials: 'include' });
  } catch (err) {
    console.warn(`[crop-health] ${path} network error`, err);
    return null;
  }
  if (!resp.ok) {
    console.warn(`[crop-health] ${path} → HTTP ${resp.status}`);
    return null;
  }
  try {
    return (await resp.json()) as T;
  } catch (err) {
    console.warn(`[crop-health] ${path} invalid JSON`, err);
    return null;
  }
}

export function navigateTo(path: string): void {
  const sdk = (window as unknown as { __NKZ_SDK__?: { navigate?: (p: string) => void } }).__NKZ_SDK__;
  if (sdk?.navigate) {
    sdk.navigate(path);
    return;
  }
  window.location.assign(path);
}

export function navigateToCropHealthParcel(parcelId: string): void {
  navigateTo(`/modules/crop-health?parcel=${encodeURIComponent(parcelId)}`);
}

export function readParcelIdFromLocation(): string | null {
  if (typeof window === 'undefined') return null;
  const params = new URLSearchParams(window.location.search);
  return params.get('parcel') || params.get('parcelId');
}

export const CROP_CONTEXT_URL = `${PLATFORM_API_BASE}/api/graph/agriculture/crop-context`;
export const PHENOLOGY_PARAMS_URL = `${PLATFORM_API_BASE}/api/graph/phenology-params`;
