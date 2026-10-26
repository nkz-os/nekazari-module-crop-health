import type { Freshness, NextJob, ParcelSummary } from '../types/assessment';

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
