import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';

export type JobStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'SUCCESS'
  | 'FAILED'
  | 'CANCELLED';

export type JobStats = {
  processing_submitted?: number;
  processing_pending?: number;
  processing_running?: number;
  processing_completed?: number;
  processing_failed?: number;
  errors?: number;
  dropped?: number;
  fetched?: number;
  indexed?: number;
  refined?: number;
  removed?: number;
  skipped?: number;
  discovered?: number;
  unique_contents?: number;
  duplicate_urls?: number;
  pending_urls?: number;
  current_board_url?: string;
  current_board_page?: number;
  collection_partial?: boolean;
  board_budget_exhausted?: boolean;
  board_active_seconds?: number;
  board_deferred?: Record<string, { url: string; reason: string }>;
  board_outcomes?: Record<string, { reason: string; page: number; url: string; partial: boolean }>;
  repeated_lists?: number;
  termination_reason?: string;
  drop_reasons?: Record<string, number>;
};

export type Job = {
  id: number;
  domain_id: number;
  job_type: string;
  seed_urls: string[] | null;
  status: JobStatus;
  triggered_by: string;
  started_at: string | null;
  finished_at: string | null;
  stats: JobStats | null;
  error_message: string | null;
  arq_job_id: string | null;
  created_at: string;
};

export const useJobs = (params: {
  domain_id?: number;
  status?: JobStatus;
  limit?: number;
} = {}) => {
  const search = new URLSearchParams();
  if (params.domain_id !== undefined) search.set('domain_id', String(params.domain_id));
  if (params.status) search.set('status', params.status);
  if (params.limit) search.set('limit', String(params.limit));
  const qs = search.toString();
  return useQuery({
    queryKey: ['jobs', params],
    queryFn: () => apiFetch<Job[]>(`/api/jobs${qs ? `?${qs}` : ''}`),
    refetchInterval: 5_000,
  });
};

export const useJob = (id: number | undefined) =>
  useQuery({
    queryKey: ['job', id],
    queryFn: () => apiFetch<Job>(`/api/jobs/${id}`),
    enabled: id !== undefined,
    refetchInterval: 3_000,
  });

export const useCancelJob = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['job', id] });
      qc.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
};

export const useTriggerFullJob = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (domain_id: number) =>
      apiFetch<Job>(`/api/jobs/full/${domain_id}`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  });
};

export const useTriggerIncrementalJob = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (domain_id: number) =>
      apiFetch<Job>(`/api/jobs/incremental/${domain_id}`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  });
};

export type CrawlResult = {
  job: Job;
  domain_host: string;
  created: boolean;
};

export const useTriggerCrawlByHost = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { input: string; job_type: 'full' | 'incremental' }) =>
      apiFetch<CrawlResult>('/api/jobs/crawl', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  });
};

export type RefreshUrlResult = {
  job_id: number;
  page_id: number;
  arq_job_id: string | null;
  created_domain: boolean;
};

export const useRefreshUrl = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { url: string; force: boolean }) =>
      apiFetch<RefreshUrlResult>('/api/jobs/refresh-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  });
};
