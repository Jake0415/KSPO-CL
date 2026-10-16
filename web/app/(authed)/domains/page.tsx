'use client';

import { useRouter } from 'next/navigation';
import { Plus } from 'lucide-react';
import { AppShell } from '@/components/AppShell';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody } from '@/components/ui/Card';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/Table';
import { useDomains } from '@/api/domains';

export default function DomainsListPage() {
  const router = useRouter();
  const { data, isLoading, isError } = useDomains();

  return (
    <AppShell
      title="데이터 소스"
      subtitle="등록된 도메인"
      breadcrumbs={['홈', '데이터 소스']}
      actions={
        <Button variant="primary" onClick={() => router.push('/domains/new')}>
          <Plus size={16} /> 새 도메인
        </Button>
      }
    >
      <Card>
        <CardBody className="px-0 py-0">
          {isLoading && <EmptyState text="도메인 목록을 불러오는 중…" />}
          {isError && <EmptyState text="도메인 목록을 불러오지 못했습니다." />}
          {data && data.length === 0 && (
            <EmptyState
              text="등록된 도메인이 없습니다."
              action={
                <Button variant="primary" onClick={() => router.push('/domains/new')}>
                  새 도메인 등록
                </Button>
              }
            />
          )}
          {data && data.length > 0 && (
            <Table>
              <THead>
                <TR>
                  <TH>호스트</TH>
                  <TH>표시명</TH>
                  <TH className="text-right tabular-nums">최대 페이지</TH>
                  <TH className="text-right tabular-nums">RPS</TH>
                  <TH>상태</TH>
                </TR>
              </THead>
              <TBody>
                {data.map((d) => (
                  <TR
                    key={d.id}
                    className="cursor-pointer"
                    onClick={() => router.push(`/domains/${d.id}`)}
                  >
                    <TD className="font-medium">{d.host}</TD>
                    <TD className="text-ink-muted">{d.display_name ?? '—'}</TD>
                    <TD className="text-right tabular-nums">{d.max_pages.toLocaleString()}</TD>
                    <TD className="text-right tabular-nums">{d.rate_limit_rps}</TD>
                    <TD>
                      <Badge variant={d.is_active ? 'success' : 'muted'}>
                        {d.is_active ? '활성' : '비활성'}
                      </Badge>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>
    </AppShell>
  );
}

function EmptyState({ text, action }: { text: string; action?: React.ReactNode }) {
  return (
    <div className="px-6 py-16 text-center">
      <p className="text-sm text-ink-muted">{text}</p>
      {action && <div className="mt-4 inline-flex">{action}</div>}
    </div>
  );
}
