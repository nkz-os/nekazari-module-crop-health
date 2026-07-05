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
      ? 'bg-red-500'
      : intent === 'warning'
        ? 'bg-amber-500'
        : intent === 'positive'
          ? 'bg-green-500'
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
    positive: 'bg-green-100 text-green-800 border border-green-200',
    warning: 'bg-amber-100 text-amber-800 border border-amber-200',
    negative: 'bg-red-100 text-red-800 border border-red-200',
    info: 'bg-blue-100 text-blue-800 border border-blue-200',
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
