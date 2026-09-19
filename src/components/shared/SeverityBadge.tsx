import React from 'react';
import { useTranslation } from '@nekazari/sdk';

export type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

// Canonical severity → semantic design-token classes (no raw palette colors).
const SEVERITY_INTENT: Record<Severity, string> = {
  LOW: 'bg-nkz-success-soft text-nkz-success-strong border border-nkz-success',
  MEDIUM: 'bg-nkz-warning-soft text-nkz-warning-strong border border-nkz-warning',
  HIGH: 'bg-nkz-danger-soft text-nkz-danger-strong border border-nkz-danger',
  CRITICAL: 'bg-nkz-danger text-nkz-text-on-accent border border-nkz-danger',
};

// CSS-variable colors for dots / sparklines / inline styles. These resolve at
// render time in the DOM (unlike Cesium, which needs concrete hex — see the
// map layer for that exception).
const SEVERITY_COLOR: Record<Severity, string> = {
  LOW: 'var(--nkz-color-success)',
  MEDIUM: 'var(--nkz-color-warning)',
  HIGH: 'var(--nkz-color-danger)',
  CRITICAL: 'var(--nkz-color-danger-strong)',
};

// Legacy shape kept for callers that build inline borders (CropHealthDetailTabs).
export const SEVERITY_STYLES: Record<Severity, { bg: string; text: string; border: string }> = {
  LOW: { bg: 'var(--nkz-color-success-soft)', text: 'var(--nkz-color-success-strong)', border: 'var(--nkz-color-success)' },
  MEDIUM: { bg: 'var(--nkz-color-warning-soft)', text: 'var(--nkz-color-warning-strong)', border: 'var(--nkz-color-warning)' },
  HIGH: { bg: 'var(--nkz-color-danger-soft)', text: 'var(--nkz-color-danger-strong)', border: 'var(--nkz-color-danger)' },
  CRITICAL: { bg: 'var(--nkz-color-danger)', text: 'var(--nkz-color-text-on-accent)', border: 'var(--nkz-color-danger-strong)' },
};

export function severityIntent(level: string): 'positive' | 'warning' | 'negative' | 'default' {
  switch ((level || '').toUpperCase()) {
    case 'LOW':
      return 'positive';
    case 'MEDIUM':
      return 'warning';
    case 'HIGH':
    case 'CRITICAL':
      return 'negative';
    default:
      return 'default';
  }
}

export function severityColor(level: string): string {
  return SEVERITY_COLOR[((level || '').toUpperCase()) as Severity] || 'var(--nkz-color-text-secondary)';
}

interface SeverityBadgeProps {
  severity: string;
  dotOnly?: boolean;
  label?: string;
}

export const SeverityBadge: React.FC<SeverityBadgeProps> = ({ severity, dotOnly = false, label }) => {
  const { t } = useTranslation('crop-health');
  const sev = (severity?.toUpperCase() || 'LOW') as Severity;
  const text = label ?? t(`severity.${sev}`, severity);

  if (dotOnly) {
    return (
      <span
        className="inline-block flex-shrink-0 rounded-full"
        style={{ width: 8, height: 8, backgroundColor: SEVERITY_COLOR[sev] || 'var(--nkz-color-text-secondary)' }}
      />
    );
  }

  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium leading-4 ${SEVERITY_INTENT[sev] || SEVERITY_INTENT.LOW}`}>
      {text}
    </span>
  );
};

export { SEVERITY_COLOR };
