/** Principal growth stages of cereals, BBCH scale (Meier 2018, CC BY 4.0). Index = first digit of the code. */
export const BBCH_PRINCIPAL_STAGES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] as const;

export const MILESTONE_ORDER = ['emergence', 'flowering_start', 'senescence_start', 'maturity'] as const;

export function parseBbch(raw: string): number | null {
  if (!/^\d{1,2}$/.test(raw.trim())) return null;
  return Number(raw.trim());
}

/** Today as YYYY-MM-DD in local time. */
export function todayIso(now: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}

export function newClientId(): string {
  const c = (globalThis as any).crypto;
  if (c?.randomUUID) return c.randomUUID();
  const b: number[] = Array.from({ length: 16 }, () => Math.floor(Math.random() * 256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = b.map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

/** Form validation; returns an i18n error key suffix or null. */
export function validateObserved(codeRaw: string, date: string, today: string): 'code' | 'date' | 'future' | null {
  if (parseBbch(codeRaw) === null) return 'code';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return 'date';
  if (date > today) return 'future';
  return null;
}
