import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api';

export type BoardSource = {
  id: number;
  domain_id: number;
  list_url: string;
  status: string;
  validation_error?: string | null;
  newest_first: boolean;
  detected_at: string;
  confirmed_at: string | null;
  last_refreshed_at: string | null;
};

export function useBoardSources(status?: string) {
  return useQuery({
    queryKey: ['board-sources', status ?? 'all'],
    queryFn: () =>
      apiFetch<BoardSource[]>(`/api/board-sources${status ? `?status=${status}` : ''}`),
  });
}

function useAction(path: (id: number) => string, method = 'POST') {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch(path(id), { method }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['board-sources'] }),
  });
}

export const useConfirmSource = () => useAction((id) => `/api/board-sources/${id}/confirm`);
export const useRejectSource = () => useAction((id) => `/api/board-sources/${id}/reject`);
export const useDeleteSource = () => useAction((id) => `/api/board-sources/${id}`, 'DELETE');

export function useAddSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { domain_id: number; list_url: string }) =>
      apiFetch('/api/board-sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['board-sources'] }),
  });
}
