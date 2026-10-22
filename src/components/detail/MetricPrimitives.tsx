import React from 'react';

export function ProgressBar({
  value,
  intent,
}: {
  value: number;
  intent?: 'positive' | 'warning' | 'negative' | 'default';
}) {
  const barCls =
    intent === 'negative'
      ? 'bg-nkz-danger'
      : intent === 'warning'
        ? 'bg-nkz-warning'
        : intent === 'positive'
          ? 'bg-nkz-success'
          : 'bg-nkz-accent-base';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-nkz-border rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${barCls}`} style={{ width: `${Math.min(value, 100)}%` }} />
      </div>
      <span className="text-sm font-mono text-nkz-text-primary">{Math.round(value)}%</span>
    </div>
  );
}

export function Badge({
  intent,
  children,
}: {
  intent?: 'positive' | 'warning' | 'negative' | 'info' | 'default';
  children: React.ReactNode;
}) {
  const cls: Record<string, string> = {
    positive: 'bg-nkz-success-soft text-nkz-success-strong border border-nkz-success',
    warning: 'bg-nkz-warning-soft text-nkz-warning-strong border border-nkz-warning',
    negative: 'bg-nkz-danger-soft text-nkz-danger-strong border border-nkz-danger',
    info: 'bg-nkz-info-soft text-nkz-info-strong border border-nkz-info',
    default: 'bg-nkz-surface-sunken text-nkz-text-secondary border border-nkz-border',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium leading-4 ${cls[intent || 'default']}`}>
      {children}
    </span>
  );
}

export function MetricSection({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`bg-nkz-surface border border-nkz-border rounded-lg p-3 ${className}`}>
      {children}
    </div>
  );
}
