import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';

export type Domain = {
  id: number;
  host: string;
  scheme: string;
  start_url?: string | null;
  display_name: string | null;
  max_depth: number;
  max_pages: number;
  rate_limit_rps: string;
  concurrency: number;
  use_playwright: boolean;
  respect_robots: boolean;
  user_agent: string | null;
  allow_patterns: string[] | null;
  deny_patterns: string[] | null;
  selector_blacklist: string[] | null;
  incremental_cron: string | null;
  incremental_enabled: boolean | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type DomainCreate = Partial<Omit<Domain, 'id' | 'created_at' | 'updated_at'>> & {
  host: string;
};

export type DomainUpdate = Partial<Omit<Domain, 'id' | 'host' | 'scheme' | 'created_at' | 'updated_at'>>;

export const useDomains = () =>
  useQuery({
    queryKey: ['domains'],
    queryFn: () => apiFetch<Domain[]>('/api/domains'),
  });

export const useDomain = (id: number | undefined) =>
  useQuery({
    queryKey: ['domain', id],
    queryFn: () => apiFetch<Domain>(`/api/domains/${id}`),
    enabled: id !== undefined,
  });

export const useCreateDomain = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DomainCreate) =>
      apiFetch<Domain>('/api/domains', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['domains'] }),
  });
};

export const useUpdateDomain = (id: number) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DomainUpdate) =>
      apiFetch<Domain>(`/api/domains/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: (data) => {
      qc.setQueryData(['domain', id], data);
      qc.invalidateQueries({ queryKey: ['domains'] });
    },
  });
};

export const useDeleteDomain = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<void>(`/api/domains/${id}`, { method: 'DELETE' }),
    onSuccess: (_data, id) => {
      qc.removeQueries({ queryKey: ['domain', id] });
      qc.invalidateQueries({ queryKey: ['domains'] });
    },
  });
};
