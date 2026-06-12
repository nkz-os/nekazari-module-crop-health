import React from 'react';

type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

const SEVERITY_INTENT: Record<Severity, { badge: string; dot: string }> = {
  LOW: { badge: 'bg-green-100 text-green-800 border border-green-200', dot: '#16a34a' },
  MEDIUM: { badge: 'bg-amber-100 text-amber-800 border border-amber-200', dot: '#d97706' },
  HIGH: { badge: 'bg-orange-100 text-orange-800 border border-orange-200', dot: '#ea580c' },
  CRITICAL: { badge: 'bg-red-100 text-red-800 border border-red-200', dot: '#dc2626' },
};

const SEVERITY_DOT_COLORS: Record<Severity, string> = {
  LOW: '#16a34a',
  MEDIUM: '#d97706',
  HIGH: '#ea580c',
  CRITICAL: '#dc2626',
};

const SEVERITY_STYLES: Record<Severity, { bg: string; text: string; border: string }> = {
  LOW: { bg: '#dcfce7', text: '#166534', border: '#16a34a' },
  MEDIUM: { bg: '#fef3c7', text: '#92400e', border: '#d97706' },
  HIGH: { bg: '#fed7aa', text: '#9a3412', border: '#ea580c' },
  CRITICAL: { bg: '#fee2e2', text: '#991b1b', border: '#dc2626' },
};

interface SeverityBadgeProps {
  severity: string;
  dotOnly?: boolean;
}

export const SeverityBadge: React.FC<SeverityBadgeProps> = ({ severity, dotOnly = false }) => {
  const sev = (severity?.toUpperCase() || 'LOW') as Severity;
  const style = SEVERITY_INTENT[sev] || SEVERITY_INTENT.LOW;

  if (dotOnly) {
    return (
      <span
        className="inline-block flex-shrink-0"
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          backgroundColor: SEVERITY_DOT_COLORS[sev] || '#6b7280',
        }}
      />
    );
  }

  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium leading-4 ${style.badge}`}>
      {severity}
    </span>
  );
};

export { SEVERITY_STYLES, SEVERITY_DOT_COLORS };
export type { Severity };
