const API_BASE = '/api/crop-health';

// Cross-module BioOrchestrator reference data lives under /api/graph, which is
// only routed on the platform API host (Traefik routes it direct to the
// bioorchestrator backend). A relative '/api/graph/...' resolves against the
// frontend host and falls through to the api-gateway auto-proxy, which has no
// 'graph' module → 404. Use the same absolute base the bioorchestrator module
// itself uses (VITE_API_URL is the platform API host, no /api suffix).
const PLATFORM_API_BASE =
  (import.meta as any).env?.VITE_API_URL || 'https://nkz.robotika.cloud';

export async function cropHealthFetch<T>(path: string): Promise<T | null> {
  try {
    const resp = await fetch(`${API_BASE}${path}`, { credentials: 'include' });
    if (!resp.ok) return null;
    return (await resp.json()) as T;
  } catch {
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
