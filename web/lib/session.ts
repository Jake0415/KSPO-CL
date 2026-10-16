import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from './api';

export type Me = { username: string; via: 'session' | 'basic' };

export const useLogin = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ username, password }: { username: string; password: string }) => {
      const body = new URLSearchParams({ username, password });
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err?.detail ?? 'login_failed');
      }
      return (await res.json()) as { ok: true; username: string };
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['session'] }),
  });
};

export const useLogout = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>('/api/auth/logout', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['session'] }),
  });
};
