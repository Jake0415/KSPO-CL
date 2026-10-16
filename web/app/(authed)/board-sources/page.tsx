'use client';

import { useState } from 'react';
import type { FormEvent } from 'react';
import { AppShell } from '@/components/AppShell';
import { Badge, type BadgeVariant } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { Input } from '@/components/ui/Input';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/Table';
import { useToast } from '@/components/ui/Toast';
import {
  type BoardSource,
  useAddSource,
  useBoardSources,
  useConfirmSource,
  useDeleteSource,
  useRejectSource,
} from '@/api/boardSources';
import { useDomains } from '@/api/domains';

const STATUS_LABELS: Record<string, string> = {
  candidate: '후보',
  confirmed: '승인',
  rejected: '거부',
  invalid: '검증 제외',
};

const STATUS_BADGE: Record<string, BadgeVariant> = {
  candidate: 'warning',
  confirmed: 'success',
  rejected: 'muted',
  invalid: 'muted',
};

type ActionState = { action: 'reject' | 'delete'; source: BoardSource } | null;

export default function BoardSourcesPage() {
  const [filter, setFilter] = useState('confirmed');
  const [actionState, setActionState] = useState<ActionState>(null);
  const [domainId, setDomainId] = useState('');
  const [listUrl, setListUrl] = useState('');

  const { data, isLoading, isError } = useBoardSources(filter);
  const { data: domains } = useDomains();
  const domainLabel = (id: number) => {
    const d = domains?.find((x) => x.id === id);
    return d ? (d.display_name ?? d.host) : `#${id}`;
  };
  const confirmMut = useConfirmSource();
  const rejectMut = useRejectSource();
  const deleteMut = useDeleteSource();
  const addMut = useAddSource();
  const { push } = useToast();

  async function handleConfirm(id: number) {
    try {
      await confirmMut.mutateAsync(id);
      push({ kind: 'success', msg: '승인됨' });
    } catch {
      push({ kind: 'error', msg: '승인에 실패했습니다.' });
    }
  }

  async function handleReject(id: number) {
    try {
      await rejectMut.mutateAsync(id);
      push({ kind: 'success', msg: '거부됨' });
    } catch {
      push({ kind: 'error', msg: '거부에 실패했습니다.' });
    }
    setActionState(null);
  }

  async function handleDelete(id: number) {
    try {
      await deleteMut.mutateAsync(id);
      push({ kind: 'success', msg: '삭제됨' });
    } catch {
      push({ kind: 'error', msg: '삭제에 실패했습니다.' });
    }
    setActionState(null);
  }

  async function handleAdd(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!domainId || !listUrl) return;
    try {
      await addMut.mutateAsync({ domain_id: Number(domainId), list_url: listUrl });
      push({ kind: 'success', msg: '추가됨' });
      setDomainId('');
      setListUrl('');
    } catch {
      push({ kind: 'error', msg: '추가에 실패했습니다.' });
    }
  }

  const actionSource = actionState?.source;

  return (
    <AppShell
      title="게시판 소스"
      subtitle="발견된 게시판은 자동 등록되어 매일 오전 4시에 최근 90일 신규 글을 수집합니다."
      breadcrumbs={['홈', '게시판 소스']}
    >
      <div className="space-y-6">
        {/* 수동 추가 폼 */}
        <Card>
          <CardHeader title="수동 추가" />
          <CardBody>
            <form onSubmit={handleAdd} className="flex items-end gap-3">
              <div className="w-64">
                <label className="block">
                  <span className="block text-sm font-medium mb-1.5 text-ink">도메인</span>
                  <select
                    value={domainId}
                    onChange={(e) => setDomainId(e.target.value)}
                    required
                    className="w-full h-control-lg px-3 rounded-md border bg-surface text-ink border-border transition-colors focus:outline-none focus:border-primary focus-visible:shadow-focus"
                  >
                    <option value="" disabled>
                      도메인 선택…
                    </option>
                    {domains?.map((d) => (
                      <option key={d.id} value={d.id}>
                        {(d.display_name ?? d.host) + ' (' + d.host + ')'}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="flex-1">
                <Input
                  label="목록 URL"
                  type="url"
                  value={listUrl}
                  onChange={(e) => setListUrl(e.target.value)}
                  placeholder="https://..."
                  required
                />
              </div>
              <Button type="submit" variant="primary" disabled={addMut.isPending}>
                {addMut.isPending ? '추가 중…' : '추가'}
              </Button>
            </form>
          </CardBody>
        </Card>

        {/* 목록 */}
        <Card>
          <CardHeader
            title="목록"
            actions={
              <div className="flex gap-1">
                {(['candidate', 'confirmed', 'rejected', 'invalid'] as const).map((s) => (
                  <Button
                    key={s}
                    size="sm"
                    variant={filter === s ? 'primary' : 'ghost'}
                    onClick={() => setFilter(s)}
                  >
                    {STATUS_LABELS[s]}
                  </Button>
                ))}
              </div>
            }
          />
          <CardBody className="px-0 py-0">
            {isLoading && <EmptyState text="불러오는 중…" />}
            {isError && <EmptyState text="목록을 불러오지 못했습니다." />}
            {data && data.length === 0 && <EmptyState text="항목이 없습니다." />}
            {data && data.length > 0 && (
              <Table>
                <THead>
                  <TR>
                    <TH>도메인</TH>
                    <TH>목록 URL</TH>
                    <TH>상태</TH>
                    <TH>탐지일</TH>
                    <TH>마지막 갱신</TH>
                    <TH />
                  </TR>
                </THead>
                <TBody>
                  {data.map((src) => (
                    <TR key={src.id}>
                      <TD className="text-ink-muted" title={`ID ${src.domain_id}`}>
                        {domainLabel(src.domain_id)}
                      </TD>
                      <TD className="font-medium max-w-xs truncate" title={src.list_url}>
                        {src.list_url}
                      </TD>
                      <TD>
                        <Badge variant={STATUS_BADGE[src.status] ?? 'muted'}>
                          <span title={src.validation_error ?? undefined}>
                            {STATUS_LABELS[src.status] ?? src.status}
                          </span>
                        </Badge>
                      </TD>
                      <TD className="text-ink-muted tabular-nums">
                        {src.detected_at
                          ? new Date(src.detected_at).toLocaleDateString('ko-KR')
                          : '—'}
                      </TD>
                      <TD className="text-ink-muted tabular-nums">
                        {src.last_refreshed_at
                          ? new Date(src.last_refreshed_at).toLocaleDateString('ko-KR')
                          : '—'}
                      </TD>
                      <TD>
                        <div className="flex gap-1 justify-end">
                          {(src.status === 'candidate' || src.status === 'invalid') && (
                            <Button
                              size="sm"
                              variant="primary"
                              onClick={() => handleConfirm(src.id)}
                              disabled={confirmMut.isPending}
                            >
                              승인
                            </Button>
                          )}
                          {src.status !== 'rejected' && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setActionState({ action: 'reject', source: src })}
                            >
                              거부
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setActionState({ action: 'delete', source: src })}
                          >
                            삭제
                          </Button>
                        </div>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardBody>
        </Card>
      </div>

      {actionSource && actionState?.action === 'reject' && (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open) setActionState(null);
          }}
          title="거부 확인"
          description={`'${actionSource.list_url}' 소스를 거부합니다.`}
          confirmText="거부"
          onConfirm={() => handleReject(actionSource.id)}
        />
      )}

      {actionSource && actionState?.action === 'delete' && (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open) setActionState(null);
          }}
          title="삭제 확인"
          description={`'${actionSource.list_url}' 소스를 영구 삭제합니다.`}
          confirmText="삭제"
          onConfirm={() => handleDelete(actionSource.id)}
        />
      )}
    </AppShell>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="px-6 py-16 text-center">
      <p className="text-sm text-ink-muted">{text}</p>
    </div>
  );
}
