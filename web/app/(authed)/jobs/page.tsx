'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { AppShell } from '@/components/AppShell';
import { Badge, type BadgeVariant } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/Table';
import { useToast } from '@/components/ui/Toast';
import { type Job, type JobStatus, useJobs, useRefreshUrl, useTriggerCrawlByHost } from '@/api/jobs';
import { useDomains } from '@/api/domains';

// 크롤 유형 — 처음 보는 사람도 알 수 있게 설명형 라벨.
const JOB_TYPE: Record<string, { label: string; desc: string }> = {
  full: { label: '전체 수집', desc: '사이트 전체를 링크 따라 훑어 새로 수집' },
  board: { label: '게시판 갱신', desc: '등록된 게시판의 최신 글만 수집' },
  incremental: { label: '변경분 갱신', desc: '이전 대비 바뀐 페이지만 갱신' },
};

const STATUS_FILTERS: { label: string; value: JobStatus | '' }[] = [
  { label: '전체', value: '' },
  { label: 'PENDING', value: 'PENDING' },
  { label: 'RUNNING', value: 'RUNNING' },
  { label: 'SUCCESS', value: 'SUCCESS' },
  { label: 'FAILED', value: 'FAILED' },
  { label: 'CANCELLED', value: 'CANCELLED' },
];

const STATUS_VARIANT: Record<JobStatus, BadgeVariant> = {
  PENDING: 'muted',
  RUNNING: 'info',
  SUCCESS: 'success',
  FAILED: 'danger',
  CANCELLED: 'warning',
};

function NewCrawlCard() {
  const [input, setInput] = useState('');
  const [jobType, setJobType] = useState<'full' | 'incremental'>('full');
  const { push } = useToast();
  const trigger = useTriggerCrawlByHost();

  const submit = () => {
    const value = input.trim();
    if (!value) {
      push({ kind: 'error', msg: '도메인을 입력하세요' });
      return;
    }
    trigger.mutate(
      { input: value, job_type: jobType },
      {
        onSuccess: (r) => {
          push({
            kind: 'success',
            msg: r.created
              ? `${r.domain_host} 자동 등록 후 크롤 시작됨`
              : `${r.domain_host} 크롤 시작됨`,
          });
          setInput('');
        },
        onError: () => push({ kind: 'error', msg: '크롤 시작 실패 — 도메인을 확인하세요' }),
      },
    );
  };

  return (
    <Card>
      <CardBody>
        <h2 className="text-sm font-semibold text-ink mb-3">새 크롤 시작</h2>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[240px]">
            <Input
              label="도메인 또는 URL"
              placeholder="www.kspo.or.kr"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submit();
              }}
            />
          </div>
          <div className="flex items-center gap-1">
            {(['full', 'incremental'] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setJobType(t)}
                title={JOB_TYPE[t]?.desc}
                className={`text-xs px-2.5 h-control-lg rounded-md border ${
                  jobType === t
                    ? 'bg-primary text-white border-primary'
                    : 'bg-bg-muted text-ink border-border hover:bg-surface-hover'
                }`}
              >
                {JOB_TYPE[t]?.label ?? t}
              </button>
            ))}
          </div>
          <Button variant="primary" onClick={submit} disabled={trigger.isPending}>
            {trigger.isPending ? '시작 중…' : '크롤 시작'}
          </Button>
        </div>
        <p className="mt-2 text-xs text-ink-muted">
          미등록 도메인은 자동 등록 후 크롤됩니다. 기본 크롤 설정(depth·pages)이 적용됩니다.
        </p>
      </CardBody>
    </Card>
  );
}

function NewUrlCrawlCard() {
  const [url, setUrl] = useState('');
  const [force, setForce] = useState(false);
  const { push } = useToast();
  const trigger = useRefreshUrl();

  const submit = () => {
    const value = url.trim();
    if (!value) {
      push({ kind: 'error', msg: 'URL을 입력하세요' });
      return;
    }
    trigger.mutate(
      { url: value, force },
      {
        onSuccess: (r) => {
          push({
            kind: 'success',
            msg: r.created_domain ? '새 도메인 등록 후 단건 수집 시작됨' : '단건 수집 시작됨',
          });
          setUrl('');
        },
        onError: () => push({ kind: 'error', msg: '단건 수집 실패 — URL을 확인하세요' }),
      },
    );
  };

  return (
    <Card>
      <CardBody>
        <h2 className="text-sm font-semibold text-ink mb-3">URL 단건 수집</h2>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[240px]">
            <Input
              label="게시물/페이지 URL"
              placeholder="https://www.kspo.or.kr/…/view.do?id=123"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submit();
              }}
            />
          </div>
          <label className="flex items-center gap-1.5 text-xs text-ink h-control-lg" title="내용 변경이 없어도 다시 정제·적재">
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
            강제 갱신
          </label>
          <Button variant="primary" onClick={submit} disabled={trigger.isPending}>
            {trigger.isPending ? '시작 중…' : '수집 시작'}
          </Button>
        </div>
        <p className="mt-2 text-xs text-ink-muted">
          URL 하나만 즉시 수집합니다. 처음 보는 주소면 도메인을 자동 등록합니다. ‘강제 갱신’은 내용 변경이 없어도 다시 적재합니다.
        </p>
      </CardBody>
    </Card>
  );
}

export default function JobsListPage() {
  const router = useRouter();
  const [status, setStatus] = useState<JobStatus | ''>('');

  const { data, isLoading, isError } = useJobs(
    status ? { status, limit: 200 } : { limit: 200 },
  );
  const { data: domains } = useDomains();
  const domainName = (id: number) => {
    const d = domains?.find((x) => x.id === id);
    return d ? (d.display_name ?? d.host) : `#${id}`;
  };

  return (
    <AppShell title="실행 이력" subtitle="Job 목록 — 5초 자동 갱신" breadcrumbs={['홈', '실행 이력']}>
      <div className="mb-4 space-y-4">
        <NewCrawlCard />
        <NewUrlCrawlCard />
      </div>
      <Card>
        <CardBody className="px-0 py-0">
          <div className="px-6 py-3 border-b border-border flex items-center gap-2">
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
          {isLoading && <Empty text="불러오는 중…" />}
          {isError && <Empty text="Job 목록을 불러오지 못했습니다." />}
          {data && data.length === 0 && <Empty text="조건에 맞는 Job이 없습니다." />}
          {data && data.length > 0 && (
            <Table>
              <THead>
                <TR>
                  <TH className="w-16">ID</TH>
                  <TH className="w-24">유형</TH>
                  <TH className="w-28">상태</TH>
                  <TH>도메인</TH>
                  <TH className="text-right tabular-nums">진행</TH>
                  <TH className="w-44">생성</TH>
                </TR>
              </THead>
              <TBody>
                {data.map((j) => (
                  <TR
                    key={j.id}
                    className="cursor-pointer"
                    onClick={() => router.push(`/jobs/${j.id}`)}
                  >
                    <TD className="font-medium tabular-nums">#{j.id}</TD>
                    <TD className="text-ink" title={JOB_TYPE[j.job_type]?.desc}>
                      {JOB_TYPE[j.job_type]?.label ?? j.job_type}
                    </TD>
                    <TD>
                      <Badge variant={STATUS_VARIANT[j.status]}>{j.status}</Badge>
                    </TD>
                    <TD className="text-ink-muted" title={`ID ${j.domain_id}`}>
                      {domainName(j.domain_id)}
                    </TD>
                    <TD className="text-right tabular-nums text-ink-muted">{summarize(j)}</TD>
                    <TD className="text-xs text-ink-muted">
                      {new Date(j.created_at).toLocaleString('ko-KR')}
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

function summarize(j: Job): string {
  const s = j.stats ?? {};
  // 처음 보는 사람도 알 수 있게: 색인(최종 저장) 위주로, 오류는 있을 때만.
  const parts = [`색인 ${s.indexed ?? 0}`, `수집 ${s.fetched ?? 0}`];
  if (s.errors) parts.push(`오류 ${s.errors}`);
  return parts.join(' · ');
}

function Empty({ text }: { text: string }) {
  return <div className="px-6 py-16 text-center text-sm text-ink-muted">{text}</div>;
}
