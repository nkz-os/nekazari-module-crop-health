import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import type { PhenologyComparisonKey, PhenologyStatus } from '../../types/assessment';

const SHOWN: PhenologyComparisonKey[] = ['heading', 'harvest'];

/** Measured error of the model in days, per group, or an explicit "not validated". */
const PhenologyValidation: React.FC<{ status: PhenologyStatus }> = ({ status }) => {
  const { t } = useTranslation('crop-health');
  if (!status.model) return null;
  const v = status.validation;
  if (v?.status !== 'measured') {
    return <p className="text-xs text-nkz-text-muted mt-2">{t('phenologyTimeline.notValidated')}</p>;
  }
  const groups = Object.entries(v.groups ?? {})
    .map(([name, cmp]) => ({ name, rows: SHOWN.filter((k) => cmp?.[k]).map((k) => ({ key: k, m: cmp[k]! })) }))
    .filter((g) => g.rows.length > 0);
  const seasons = v.dataset?.seasons ?? [];
  const seasonRange = seasons.length
    ? (seasons[0] === seasons[seasons.length - 1] ? String(seasons[0]) : `${seasons[0]}–${seasons[seasons.length - 1]}`)
    : '';
  return (
    <div className="mt-2">
      <p className="text-xs font-semibold text-nkz-text-primary mb-1">{t('phenologyTimeline.validation')}</p>
      {groups.map((g) => (
        <div key={g.name} className="mb-1">
          <p className="text-xs text-nkz-text-primary">{t(`phenologyTimeline.validationGroupName.${g.name}`, g.name)}</p>
          <ul className="space-y-0.5">
            {g.rows.map(({ key, m }) => (
              <li key={key} className="text-xs text-nkz-text-secondary">
                {t('phenologyTimeline.validationError', {
                  name: t(`phenologyTimeline.validationGroup.${key}`, key),
                  mae: m.mae_days.toFixed(1),
                  n: m.n,
                })}
                {' · '}
                {Math.abs(m.bias_days) < 0.5
                  ? t('phenologyTimeline.validationBiasNone')
                  : m.bias_days < 0
                    ? t('phenologyTimeline.validationBiasEarly', { days: Math.abs(m.bias_days).toFixed(1) })
                    : t('phenologyTimeline.validationBiasLate', { days: m.bias_days.toFixed(1) })}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {v.dataset?.name && (
        <p className="text-xs text-nkz-text-muted mt-1">
          {t('phenologyTimeline.validationDataset', { name: v.dataset.name, seasons: seasonRange })}
          {typeof v.dataset.sheets === 'number' && ` · ${t('phenologyTimeline.validationSheets', { count: v.dataset.sheets })}`}
        </p>
      )}
    </div>
  );
};

export default PhenologyValidation;
