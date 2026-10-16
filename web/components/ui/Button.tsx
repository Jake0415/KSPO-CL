'use client';

import type { ButtonHTMLAttributes } from 'react';
import { clsx } from 'clsx';

type Variant = 'primary' | 'ghost' | 'destructive' | 'secondary';
type Size = 'sm' | 'md';

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
};

const variantClass: Record<Variant, string> = {
  primary: 'bg-primary text-white hover:bg-primary-hover disabled:opacity-50',
  secondary: 'bg-bg-muted text-ink hover:bg-surface-hover disabled:opacity-50',
  ghost: 'text-ink hover:bg-bg-muted',
  destructive: 'bg-danger text-white hover:bg-danger-hover disabled:opacity-50',
};

const sizeClass: Record<Size, string> = {
  sm: 'h-control-sm px-3 text-sm',
  md: 'h-control-md px-4 text-md',
};

export function Button({
  variant = 'secondary',
  size = 'md',
  className,
  type = 'button',
  ...rest
}: Props) {
  return (
    <button
      type={type}
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors',
        'focus:outline-none focus-visible:shadow-focus',
        variantClass[variant],
        sizeClass[size],
        className,
      )}
      {...rest}
    />
  );
}
