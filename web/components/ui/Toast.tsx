'use client';

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from 'react';
import { AlertCircle, CheckCircle2, Info } from 'lucide-react';

type Kind = 'success' | 'error' | 'info';
type Toast = { id: string; kind: Kind; msg: string };

type Ctx = { push: (t: Omit<Toast, 'id'>) => void };

const ToastCtx = createContext<Ctx | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);

  const push = useCallback((t: Omit<Toast, 'id'>) => {
    const id =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`;
    setItems((prev) => [...prev, { ...t, id }]);
    setTimeout(() => {
      setItems((prev) => prev.filter((x) => x.id !== id));
    }, 4000);
  }, []);

  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div
        role="region"
        aria-live="polite"
        className="fixed top-4 right-4 z-toast flex flex-col gap-2 pointer-events-none"
      >
        {items.map((t) => {
          const cfg = config[t.kind];
          return (
            <div
              key={t.id}
              role="status"
              className={
                'pointer-events-auto bg-surface border border-border shadow-md rounded-md px-4 py-3 ' +
                'flex items-center gap-2 min-w-[260px] border-l-4 ' +
                cfg.borderColor
              }
            >
              <cfg.Icon size={16} className={cfg.iconColor} />
              <span className="text-sm">{t.msg}</span>
            </div>
          );
        })}
      </div>
    </ToastCtx.Provider>
  );
}

const config: Record<Kind, { Icon: typeof Info; borderColor: string; iconColor: string }> = {
  success: { Icon: CheckCircle2, borderColor: 'border-l-success', iconColor: 'text-success' },
  error:   { Icon: AlertCircle,  borderColor: 'border-l-danger',  iconColor: 'text-danger' },
  info:    { Icon: Info,         borderColor: 'border-l-primary', iconColor: 'text-primary' },
};

export function useToast(): Ctx {
  const ctx = useContext(ToastCtx);
  if (!ctx) {
    throw new Error('useToast must be used within ToastProvider');
  }
  return ctx;
}
