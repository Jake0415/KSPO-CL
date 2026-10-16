import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';

export type PageStatus =
  | 'DISCOVERED'
  | 'FETCHED'
  | 'CLEANED'
  | 'REFINED'
  | 'INDEXED'
  | 'DROPPED'
  | 'ERROR'
  | 'REMOVED';

export type PageRow = {
  id: number;
  domain_id: number;
  url: string;
  url_hash: string;
  title: string | null;
  status: PageStatus;
  drop_reason: string | null;
  http_status: number | null;
  last_http_status: number | null;
  content_type: string | null;
  content_hash: string | null;
  depth: number;
  error_count: number;
  discovered_at: string;
  last_fetched_at: string | null;
  last_indexed_at: string | null;
};

export type PageChunkRow = {
  id: number;
  chunk_index: number;
  is_attachment: boolean;
  attachment_id: number | null;
  token_len: number;
  embedding_model: string | null;
  embed_status: string;
  kb_status: string;
};

export type PageDetail = PageRow & {
  chunks: PageChunkRow[];
  attachments_count: number;
};

export const usePages = (params: {
  domain_id?: number;
  status?: PageStatus | '';
  q?: string;
  limit?: number;
  offset?: number;
} = {}) => {
  const search = new URLSearchParams();
  if (params.domain_id !== undefined) search.set('domain_id', String(params.domain_id));
  if (params.status) search.set('status', params.status);
  if (params.q) search.set('q', params.q);
  if (params.limit) search.set('limit', String(params.limit));
  if (params.offset) search.set('offset', String(params.offset));
  const qs = search.toString();
  return useQuery({
    queryKey: ['pages', params],
    queryFn: () => apiFetch<PageRow[]>(`/api/pages${qs ? `?${qs}` : ''}`),
  });
};

export const usePage = (id: number | undefined) =>
  useQuery({
    queryKey: ['page', id],
    queryFn: () => apiFetch<PageDetail>(`/api/pages/${id}`),
    enabled: id !== undefined,
  });
