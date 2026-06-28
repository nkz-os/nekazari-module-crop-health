const API_BASE = '/api/crop-health';

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

export const CROP_CONTEXT_URL = '/api/graph/agriculture/crop-context';
export const PHENOLOGY_PARAMS_URL = '/api/graph/phenology-params';
