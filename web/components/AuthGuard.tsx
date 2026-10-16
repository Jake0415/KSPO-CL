'use client';

import type { ReactNode } from 'react';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';

type Me = { username: string; via: 'session' | 'basic' };

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['session'],
    queryFn: () => apiFetch<Me>('/api/auth/me'),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!isLoading && (isError || !data)) {
      router.replace('/login');
    }
  }, [isLoading, isError, data, router]);

  if (isLoading) {
    return (
      <div className="min-h-screen grid place-items-center text-ink-muted text-sm">
        세션 확인 중…
      </div>
    );
  }
  if (isError || !data) {
    return null;
  }
  return <>{children}</>;
}
