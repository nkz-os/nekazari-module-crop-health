import React from 'react';

type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

const SEVERITY_STYLES: Record<Severity, { bg: string; text: string; border: string }> = {
  LOW: { bg: '#dcfce7', text: '#166534', border: '#16a34a' },
  MEDIUM: { bg: '#fef3c7', text: '#92400e', border: '#d97706' },
  HIGH: { bg: '#fed7aa', text: '#9a3412', border: '#ea580c' },
  CRITICAL: { bg: '#fee2e2', text: '#991b1b', border: '#dc2626' },
};

const SEVERITY_DOT_COLORS: Record<Severity, string> = {
  LOW: '#16a34a',
  MEDIUM: '#d97706',
  HIGH: '#ea580c',
  CRITICAL: '#dc2626',
};

interface SeverityBadgeProps {
  severity: string;
  dotOnly?: boolean;
}

export const SeverityBadge: React.FC<SeverityBadgeProps> = ({ severity, dotOnly = false }) => {
  const sev = (severity?.toUpperCase() || 'LOW') as Severity;
  const style = SEVERITY_STYLES[sev] || SEVERITY_STYLES.LOW;

  if (dotOnly) {
    return (
      <span
        style={{
          display: 'inline-block',
          width: 8,
          height: 8,
          borderRadius: '50%',
          backgroundColor: SEVERITY_DOT_COLORS[sev] || '#6b7280',
          flexShrink: 0,
        }}
      />
    );
  }

  return (
    <span
      style={{
        background: style.bg,
        color: style.text,
        border: `1px solid ${style.border}`,
        padding: '2px 8px',
        borderRadius: 4,
        fontSize: '0.75rem',
        fontWeight: 600,
      }}
    >
      {severity}
    </span>
  );
};

export { SEVERITY_STYLES, SEVERITY_DOT_COLORS };
