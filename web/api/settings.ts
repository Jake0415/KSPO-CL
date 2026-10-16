import { useMutation, useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';

export type EnvEntry = { key: string; value: string; masked: boolean };
export type EnvMirror = { entries: EnvEntry[] };

export const useEnvMirror = () =>
  useQuery({
    queryKey: ['settings', 'env'],
    queryFn: () => apiFetch<EnvMirror>('/api/settings/env'),
  });

export type ChangePasswordBody = { current_password: string; new_password: string };

export const useChangePassword = () =>
  useMutation({
    mutationFn: (body: ChangePasswordBody) =>
      apiFetch<void>('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
  });
