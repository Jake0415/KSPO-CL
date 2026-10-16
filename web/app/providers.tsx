'use client';

import { useState, type ReactNode } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { ToastProvider } from '@/components/ui/Toast';
import { makeQueryClient } from '@/lib/queryClient';

export function Providers({ children }: { children: ReactNode }) {
  // QueryClient를 컴포넌트 내부 state에 저장 — Next.js HMR/리렌더 시 재생성 방지
  const [queryClient] = useState(() => makeQueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  );
}
