import type { ReactNode } from 'react';
import { clsx } from 'clsx';
import { CheckCircle2, Circle, AlertTriangle, AlertCircle } from 'lucide-react';

export type BadgeVariant = 'success' | 'muted' | 'warning' | 'danger' | 'info';

const variants: Record<
  BadgeVariant,
  { bg: string; fg: string; icon: typeof Circle }
> = {
  success: { bg: 'bg-success-soft', fg: 'text-success', icon: CheckCircle2 },
  muted:   { bg: 'bg-bg-muted',     fg: 'text-ink-muted', icon: Circle },
  warning: { bg: 'bg-warning-soft', fg: 'text-warning', icon: AlertTriangle },
  danger:  { bg: 'bg-danger-soft',  fg: 'text-danger', icon: AlertCircle },
  info:    { bg: 'bg-info-soft',    fg: 'text-info', icon: Circle },
};

export function Badge({
  variant = 'muted',
  children,
}: {
  variant?: BadgeVariant;
  children: ReactNode;
}) {
  const { bg, fg, icon: Icon } = variants[variant];
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 px-2 h-6 rounded-md text-xs font-medium',
        bg,
        fg,
      )}
    >
      <Icon size={12} />
      <span>{children}</span>
    </span>
  );
}
