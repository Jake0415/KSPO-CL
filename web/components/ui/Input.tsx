'use client';

import { forwardRef } from 'react';
import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react';
import { clsx } from 'clsx';

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  label?: string;
  hint?: string;
  error?: string;
};

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, hint, error, className, id, ...rest }, ref) => {
    const inputId = id ?? rest.name;
    return (
      <label className="block">
        {label && (
          <span className="block text-sm font-medium mb-1.5 text-ink">{label}</span>
        )}
        <input
          ref={ref}
          id={inputId}
          className={clsx(
            'w-full h-control-lg px-3 rounded-md border bg-surface text-ink',
            'transition-colors focus:outline-none focus-visible:shadow-focus',
            error ? 'border-danger' : 'border-border focus:border-primary',
            className,
          )}
          {...rest}
        />
        {error ? (
          <span className="block mt-1 text-sm text-danger">{error}</span>
        ) : (
          hint && <span className="block mt-1 text-sm text-ink-muted">{hint}</span>
        )}
      </label>
    );
  },
);
Input.displayName = 'Input';

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label?: string;
  hint?: string;
  error?: string;
};

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, hint, error, className, id, rows = 4, ...rest }, ref) => {
    const inputId = id ?? rest.name;
    return (
      <label className="block">
        {label && (
          <span className="block text-sm font-medium mb-1.5 text-ink">{label}</span>
        )}
        <textarea
          ref={ref}
          id={inputId}
          rows={rows}
          className={clsx(
            'w-full px-3 py-2 rounded-md border bg-surface text-ink',
            'transition-colors focus:outline-none focus-visible:shadow-focus',
            error ? 'border-danger' : 'border-border focus:border-primary',
            'font-mono text-sm',
            className,
          )}
          {...rest}
        />
        {error ? (
          <span className="block mt-1 text-sm text-danger">{error}</span>
        ) : (
          hint && <span className="block mt-1 text-sm text-ink-muted">{hint}</span>
        )}
      </label>
    );
  },
);
Textarea.displayName = 'Textarea';
