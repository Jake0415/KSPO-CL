'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { AppShell } from '@/components/AppShell';
import { Badge, type BadgeVariant } from '@/components/ui/Badge';
import { Card, CardBody } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/Table';
import { type PageStatus, usePages } from '@/api/pages';

const STATUS_FILTERS: { label: string; value: PageStatus | '' }[] = [
  { label: '전체', value: '' },
  { label: 'INDEXED', value: 'INDEXED' },
  { label: 'DROPPED', value: 'DROPPED' },
  { label: 'ERROR', value: 'ERROR' },
  { label: 'REMOVED', value: 'REMOVED' },
];

const STATUS_VARIANT: Record<PageStatus, BadgeVariant> = {
  DISCOVERED: 'muted',
  FETCHED: 'info',
  CLEANED: 'info',
  REFINED: 'info',
  INDEXED: 'success',
  DROPPED: 'warning',
  ERROR: 'danger',
  REMOVED: 'muted',
};

export default function PagesSearchPage() {
  const router = useRouter();
  const [status, setStatus] = useState<PageStatus | ''>('');
  const [q, setQ] = useState('');

  const { data, isLoading, isError } = usePages({
    status: status || undefined,
    q: q || undefined,
    limit: 200,
  });

  return (
    <AppShell title="페이지" subtitle="크롤된 페이지 검색" breadcrumbs={['홈', '페이지']}>
      <div className="space-y-4">
        <Card>
          <CardBody className="space-y-3">
            <Input
              label="검색어"
              placeholder="URL 또는 제목 부분 일치"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <div className="flex items-center gap-2">
              {STATUS_FILTERS.map((f) => (
                <button
                  key={f.value || 'all'}
                  onClick={() => setStatus(f.value)}
                  className={`text-xs px-2.5 h-7 rounded-md ${
                    status === f.value ? 'bg-primary text-white' : 'bg-bg-muted text-ink hover:bg-surface-hover'
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardBody className="px-0 py-0">
            {isLoading && <Empty text="불러오는 중…" />}
            {isError && <Empty text="페이지 목록 조회 실패" />}
            {data && data.length === 0 && <Empty text="결과가 없습니다." />}
            {data && data.length > 0 && (
              <Table>
                <THead>
                  <TR>
                    <TH className="w-16">ID</TH>
                    <TH className="w-28">상태</TH>
                    <TH>URL / 제목</TH>
                    <TH className="w-20 text-right tabular-nums">depth</TH>
                    <TH className="w-44">last fetch</TH>
                  </TR>
                </THead>
                <TBody>
                  {data.map((p) => (
                    <TR
                      key={p.id}
                      className="cursor-pointer"
                      onClick={() => router.push(`/pages/${p.id}`)}
                    >
                      <TD className="font-medium tabular-nums">#{p.id}</TD>
                      <TD>
                        <Badge variant={STATUS_VARIANT[p.status]}>{p.status}</Badge>
                      </TD>
                      <TD>
                        <div className="font-medium">{p.title ?? '(제목 없음)'}</div>
                        <div className="text-xs text-ink-muted truncate max-w-[600px]">{p.url}</div>
                      </TD>
                      <TD className="text-right tabular-nums">{p.depth}</TD>
                      <TD className="text-xs text-ink-muted">
                        {p.last_fetched_at ? new Date(p.last_fetched_at).toLocaleString('ko-KR') : '-'}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardBody>
        </Card>
      </div>
    </AppShell>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="px-6 py-16 text-center text-sm text-ink-muted">{text}</div>;
}
