import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Sprout } from 'lucide-react';
import { SlotShell } from '@nekazari/viewer-kit';
import { cropHealthFetch, navigateToCropHealthParcel } from '../api/cropHealthApi';
import { CROP_HEALTH_ACCENT } from '../constants';
import { SeverityBadge } from './shared/SeverityBadge';
import type { AssessmentData } from '../types/assessment';

type ActionKey = 'NO_ACTION' | 'MONITOR' | 'IRRIGATE_SCHEDULED' | 'IRRIGATE_IMMEDIATE';

const ACTION_LABELS: Record<ActionKey, string> = {
  NO_ACTION: 'action.noAction',
  MONITOR: 'action.monitor',
  IRRIGATE_SCHEDULED: 'action.irrigateScheduled',
  IRRIGATE_IMMEDIATE: 'action.irrigateImmediate',
};

function MiniProgress({ value, intent }: { value: number; intent: 'positive' | 'warning' | 'negative' }) {
  const barCls = intent === 'negative' ? 'bg-red-500' : intent === 'warning' ? 'bg-amber-500' : 'bg-green-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-nkz-border rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${barCls}`} style={{ width: `${Math.min(value, 100)}%` }} />
      </div>
      <span className="text-xs font-mono text-nkz-text-primary w-8 text-right">{Math.round(value)}%</span>
    </div>
  );
}

const CropHealthWidget: React.FC = () => {
  const { t } = useTranslation('crop-health');
  const [assessments, setAssessments] = useState<AssessmentData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchAssessments = async () => {
      try {
        const data = await cropHealthFetch<{ assessments: AssessmentData[] }>('/assessments/latest');
        setAssessments(data?.assessments ?? []);
        if (!data) setError('fetch failed');
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'error');
      } finally {
        setLoading(false);
      }
    };

    fetchAssessments();
    const interval = setInterval(fetchAssessments, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <SlotShell moduleId="crop-health" title={t('title')} icon={<Sprout className="w-4 h-4" />} accent={CROP_HEALTH_ACCENT}>
      {loading && (
        <div className="space-y-2">
          <div className="animate-pulse h-16 bg-nkz-border rounded-lg" />
          <div className="animate-pulse h-16 bg-nkz-border rounded-lg" />
        </div>
      )}

      {!loading && error && (
        <p className="text-sm text-nkz-text-muted text-center">{t('error')}: {error}</p>
      )}

      {!loading && !error && assessments.length === 0 && (
        <div className="text-center py-2">
          <p className="text-sm text-nkz-text-secondary">{t('noAssessments')}</p>
          <p className="text-xs text-nkz-text-muted mt-1">{t('noAssessmentsHint')}</p>
        </div>
      )}

      {!loading && !error && assessments.length > 0 && (
        <div className="space-y-2">
          {assessments.map((a) => (
            <div key={a.id || a.parcelId} className="bg-nkz-surface border border-nkz-border rounded-lg p-2.5">
              <div className="flex items-center justify-between mb-2 gap-2">
                <button
                  type="button"
                  className="text-sm font-semibold text-nkz-text-primary hover:text-nkz-accent-base transition-colors truncate bg-transparent border-none cursor-pointer p-0"
                  onClick={() => a.parcelId && navigateToCropHealthParcel(a.parcelId)}
                >
                  {a.parcelName || a.parcelId}
                </button>
                <SeverityBadge severity={a.overallSeverity} />
              </div>

              <div className="grid grid-cols-2 gap-2">
                {a.cwsiValue !== undefined && (
                  <div>
                    <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">{t('metrics.cwsi')}</span>
                    <MiniProgress value={a.cwsiValue * 100} intent={a.cwsiValue > 0.6 ? 'negative' : a.cwsiValue > 0.3 ? 'warning' : 'positive'} />
                  </div>
                )}
                {a.compositeStressIndex !== undefined && (
                  <div>
                    <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">{t('metrics.stress')}</span>
                    <MiniProgress value={a.compositeStressIndex} intent={a.compositeStressIndex > 75 ? 'negative' : a.compositeStressIndex > 50 ? 'warning' : 'positive'} />
                  </div>
                )}
                {a.vigorIndex !== undefined && (
                  <div>
                    <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">{t('vigor')}</span>
                    <MiniProgress value={a.vigorIndex * 100} intent={a.vigorIndex > 0.6 ? 'positive' : a.vigorIndex > 0.3 ? 'warning' : 'negative'} />
                  </div>
                )}
                {a.yieldUtilizationPct !== undefined && (
                  <div>
                    <span className="text-xs text-nkz-text-secondary font-medium uppercase tracking-wider">{t('metrics.yield')}</span>
                    <MiniProgress value={a.yieldUtilizationPct} intent={a.yieldUtilizationPct > 80 ? 'positive' : a.yieldUtilizationPct > 60 ? 'warning' : 'negative'} />
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between mt-2 pt-2 border-t border-nkz-border text-xs">
                <span className="font-semibold text-nkz-text-primary">
                  {t(ACTION_LABELS[a.recommendedAction as ActionKey] || a.recommendedAction)}
                </span>
                <span className="text-nkz-text-muted">
                  {a.phenologySource === 'bioorchestrator' ? t('metrics.bioSource') : t('defaultParams')}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </SlotShell>
  );
};

export default CropHealthWidget;
