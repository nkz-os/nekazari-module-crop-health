import type { TFunction } from 'i18next';

export function formatRelativeTime(iso: string | undefined | null, t: TFunction): string {
  if (!iso) return '—';
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return t('relativeTime.now');
    if (mins < 60) return t('relativeTime.minutes', { count: mins });
    const hours = Math.floor(mins / 60);
    if (hours < 24) return t('relativeTime.hours', { count: hours });
    return t('relativeTime.days', { count: Math.floor(hours / 24) });
  } catch {
    return iso.slice(0, 10);
  }
}
