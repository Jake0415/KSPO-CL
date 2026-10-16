'use client';

import { forwardRef } from 'react';
import type { InputHTMLAttributes } from 'react';
import { clsx } from 'clsx';

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & {
  label?: string;
};

export const Checkbox = forwardRef<HTMLInputElement, Props>(({ label, className, ...rest }, ref) => {
  return (
    <label className="inline-flex items-center gap-2 cursor-pointer select-none">
      <input
        ref={ref}
        type="checkbox"
        className={clsx(
          'h-4 w-4 rounded border-border accent-primary',
          'focus-visible:shadow-focus',
          className,
        )}
        {...rest}
      />
      {label && <span className="text-sm text-ink">{label}</span>}
    </label>
  );
});
Checkbox.displayName = 'Checkbox';
