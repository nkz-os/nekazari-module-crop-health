import type { Freshness, NextJob, ParcelSummary, PlannedCrop } from '../types/assessment';

export function jobLabelKey(job: NextJob | null): string {
  return job ? `worklist.job.${job.kind}` : 'worklist.job.none';
}

export function whenLabel(
  job: NextJob | null,
  t: (key: string) => string,
  lang: string,
): string {
  if (!job || !job.when) return '';
  if (job.when === 'today') return t('worklist.when.today');
  return new Date(job.when).toLocaleDateString(lang);
}

export function freshnessTone(f: Freshness): 'muted' | 'warning' | 'danger' {
  if (f === 'aging') return 'warning';
  if (f === 'stale') return 'danger';
  return 'muted';
}

export function semaphore(row: ParcelSummary): 'red' | 'amber' | 'green' | 'grey' {
  if (row.cropStatus === 'none' || !row.hasData) return 'grey';
  const sev = (row.overallSeverity ?? '').toUpperCase();
  if (row.surprise || sev === 'CRITICAL' || sev === 'HIGH') return 'red';
  if (row.nextJob?.when === 'today' || sev === 'MEDIUM') return 'amber';
  return 'green';
}

type JobT = (key: string, opts?: Record<string, unknown>) => string;

function localDate(value: string, t: JobT, lang: string): string {
  return value === 'today' ? t('worklist.when.today') : new Date(value).toLocaleDateString(lang);
}

/** The one-line text of a job, or null when there is nothing to say (calm parcel, no date). */
export function jobText(
  job: NextJob | null,
  t: JobT,
  lang: string,
  plannedCrop?: PlannedCrop | null,
): string | null {
  if (!job) return null;
  const d = (job.detail ?? {}) as Record<string, unknown>;
  const when = job.when ? localDate(job.when, t, lang) : '';
  switch (job.kind) {
    case 'none_until': {
      if (typeof d.date !== 'string' || !d.date) return null;
      return t('worklist.job.none_until', { date: localDate(d.date, t, lang) });
    }
    case 'irrigate':
      return d.scheduled ? t('action.irrigateScheduled') : t('worklist.job.irrigate');
    case 'sow': {
      const base = lang.split('-')[0];
      const crop = plannedCrop?.names?.[lang] ?? plannedCrop?.names?.[base] ?? d.crop ?? d.species;
      const label = t('worklist.job.sow', { crop });
      if (!job.when) return `${label}: ${t('worklist.when.noDate')}`;
      const w = d.workability;
      const work = w === 'optimal' || w === 'too_wet' || w === 'too_dry' ? `: ${t(`worklist.workability.${w}`)}` : '';
      return `${label}${work} · ${when}`;
    }
    case 'treat': {
      const code = String(d.disease ?? '');
      const label = t('worklist.job.treat', { disease: t(`disease.${code}`, { defaultValue: code }) });
      return when ? `${label} · ${when}` : label;
    }
    default: {
      const label = t(jobLabelKey(job), d);
      return when ? `${label} · ${when}` : label;
    }
  }
}
