import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';

export type Overview = {
  sites_total: number;
  sites_active: number;
  docs_total: number;
  docs_by_status: Record<string, number>;
  chunks_total: number;
  embeddings_total: number;
  failed_crawls: number;
  running_crawls: number;
  new_docs_today: number;
  updated_docs_today: number;
  last_crawl_at: string | null;
  last_embed_at: string | null;
  crawl_health_pct: number;
  system_health: string;
};

export type UnitCount = { key: string; count: number };

export type SiteSummary = {
  domain_id: number;
  host: string;
  is_active: boolean;
  max_depth: number;
  max_pages: number;
  use_playwright: boolean;
  indexed: number;
  total: number;
  last_crawl_at: string | null;
  schedule: string;
};

export type SiteStructure = {
  domain_id: number;
  host: string;
  is_active: boolean;
  max_depth: number;
  max_pages: number;
  total_pages: number;
  by_status: UnitCount[];
  by_depth: UnitCount[];
  url_patterns: UnitCount[];
  attachments: number;
  last_crawl_at: string | null;
  schedule: string;
  board_source_count: number;
};

export const useSitesList = () =>
  useQuery({
    queryKey: ['console', 'sites'],
    queryFn: () => apiFetch<SiteSummary[]>('/api/console/sites'),
  });

export type ChunkText = { point_id: string; text: string; tags: string[] };

export const useOverview = () =>
  useQuery({
    queryKey: ['console', 'overview'],
    queryFn: () => apiFetch<Overview>('/api/console/overview'),
    refetchInterval: 30_000,
  });

export const useSiteStructure = (domainId: number | undefined) =>
  useQuery({
    queryKey: ['console', 'structure', domainId],
    queryFn: () => apiFetch<SiteStructure>(`/api/console/sites/${domainId}/structure`),
    enabled: domainId !== undefined,
  });

export const usePageChunks = (pageId: number | undefined) =>
  useQuery({
    queryKey: ['console', 'chunks', pageId],
    queryFn: () => apiFetch<ChunkText[]>(`/api/console/pages/${pageId}/chunks`),
    enabled: pageId !== undefined,
  });
