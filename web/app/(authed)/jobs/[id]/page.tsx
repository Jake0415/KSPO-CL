'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { AppShell } from '@/components/AppShell';
import { Badge, type BadgeVariant } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { useToast } from '@/components/ui/Toast';
import { type Job, type JobStatus, useCancelJob, useJob } from '@/api/jobs';

const STATUS_VARIANT: Record<JobStatus, BadgeVariant> = {
  PENDING: 'muted',
  RUNNING: 'info',
  SUCCESS: 'success',
  FAILED: 'danger',
  CANCELLED: 'warning',
};

const JOB_TYPE_LABEL: Record<string, string> = {
  full: '전체 수집',
  board: '게시판 갱신',
  incremental: '변경분 갱신',
};

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const jobId = params?.id ? Number(params.id) : undefined;
  const { data, isLoading, isError } = useJob(jobId);
  const cancelMut = useCancelJob();
  const { push } = useToast();
  const [confirmOpen, setConfirmOpen] = useState(false);

  if (isLoading) {
    return (
      <AppShell title="Job 상세" breadcrumbs={['홈', '실행 이력', '상세']}>
        <Card><CardBody><p className="text-sm text-ink-muted">불러오는 중…</p></CardBody></Card>
      </AppShell>
    );
  }
  if (isError || !data || jobId === undefined) {
    return (
      <AppShell title="Job 상세" breadcrumbs={['홈', '실행 이력', '상세']}>
        <Card><CardBody><p className="text-sm text-ink-muted">Job을 찾을 수 없습니다.</p></CardBody></Card>
      </AppShell>
    );
  }

  const cancelable = data.status === 'PENDING' || data.status === 'RUNNING';

  async function performCancel() {
    if (jobId === undefined) return;
    try {
      await cancelMut.mutateAsync(jobId);
      push({ kind: 'success', msg: 'Job 취소 요청됨 — 다음 task 진입 시 종료' });
    } catch {
      push({ kind: 'error', msg: 'Job 취소 실패' });
    }
  }

  return (
    <AppShell
      title={`Job #${data.id}`}
      subtitle={`${JOB_TYPE_LABEL[data.job_type] ?? data.job_type} · ${data.triggered_by}`}
      breadcrumbs={['홈', '실행 이력', `#${data.id}`]}
      actions={
        <>
          <Badge variant={STATUS_VARIANT[data.status]}>{data.status}</Badge>
          {cancelable && (
            <Button
              variant="destructive"
              onClick={() => setConfirmOpen(true)}
              disabled={cancelMut.isPending}
            >
              {cancelMut.isPending ? '취소 중…' : '취소'}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-6 max-w-form">
        <Card>
          <CardHeader title="메타" />
          <CardBody className="text-sm space-y-1.5">
            <Row k="ID" v={`#${data.id}`} />
            <Row k="도메인" v={`#${data.domain_id}`} />
            <Row k="유형" v={JOB_TYPE_LABEL[data.job_type] ?? data.job_type} />
            <Row k="ARQ Job ID" v={data.arq_job_id ?? '-'} mono />
            <Row k="시드 URL" v={data.seed_urls?.join(', ') ?? '-'} mono />
            <Row k="생성" v={new Date(data.created_at).toLocaleString('ko-KR')} />
            <Row
              k="시작"
              v={data.started_at ? new Date(data.started_at).toLocaleString('ko-KR') : '-'}
            />
            <Row
              k="종료"
              v={data.finished_at ? new Date(data.finished_at).toLocaleString('ko-KR') : '-'}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="진행 통계" description="이 작업이 처리한 페이지 집계 (수집 → 정제 → 색인 순서)" />
          <CardBody>
            <StatsGrid stats={data.stats} />
            <p className="mt-3 text-sm">종료 사유: {data.stats?.termination_reason === 'url_limit'
              ? '수집 URL 제한 도달 (최대 2,000개)' : data.stats?.termination_reason === 'queue_exhausted'
              ? '방문 대기 URL 소진' : data.status === 'CANCELLED' ? '사용자 취소'
              : data.status === 'FAILED' ? (data.error_message ?? '작업 실패')
              : data.status === 'RUNNING' ? '수집 진행 중' : '기록 없음'}</p>
          </CardBody>
        </Card>

        {data.error_message && (
          <Card className="border-danger/30">
            <CardHeader title="에러 메시지" />
            <CardBody>
              <pre className="text-xs bg-bg-muted p-3 rounded font-mono whitespace-pre-wrap">
                {data.error_message}
              </pre>
            </CardBody>
          </Card>
        )}
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`Job #${data.id} 취소`}
        description="진행 중인 task는 자연 완료 후 다음 task 진입 시 즉시 종료됩니다."
        confirmText="취소 요청"
        onConfirm={() => {
          setConfirmOpen(false);
          void performCancel();
        }}
      />
    </AppShell>
  );
}

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex">
      <span className="w-32 text-ink-muted">{k}</span>
      <span className={mono ? 'font-mono text-xs' : ''}>{v}</span>
    </div>
  );
}

function StatsGrid({ stats }: { stats: Job['stats'] }) {
  const s = stats ?? {};
  // key, 한글 라벨, 설명 — 처음 보는 사람도 이해할 수 있게.
  const items: { k: string; label: string; desc: string; v: number; accent?: 'good' | 'mute' }[] = [
    { k: 'discovered', label: '발견', desc: '링크에서 찾아낸 페이지 수', v: s.discovered ?? 0 },
    { k: 'fetched', label: '수집', desc: '실제로 내려받은 페이지', v: s.fetched ?? 0 },
    { k: 'skipped', label: '건너뜀', desc: '내용이 그대로여서 재처리 생략', v: s.skipped ?? 0, accent: 'mute' },
    { k: 'refined', label: '정제', desc: '본문 정리·요약을 마친 페이지', v: s.refined ?? 0 },
    { k: 'indexed', label: '색인 완료', desc: '검색에 저장된 최종 결과 (핵심 성과)', v: s.indexed ?? 0, accent: 'good' },
    { k: 'dropped', label: '제외', desc: '품질 기준 미달로 색인하지 않음', v: s.dropped ?? 0, accent: 'mute' },
    { k: 'errors', label: '응답 실패', desc: '상대 사이트가 응답하지 않은 페이지 — 대개 그쪽 서버 문제라 정상', v: s.errors ?? 0, accent: 'mute' },
    { k: 'unique_contents', label: '고유 콘텐츠', desc: '수집·정제 가능한 본문의 고유 해시 수', v: s.unique_contents ?? 0 },
    { k: 'duplicate_urls', label: '중복 URL', desc: '방문 큐 재등록을 차단한 횟수', v: s.duplicate_urls ?? 0 },
    { k: 'pending_urls', label: '대기 URL', desc: '방문 큐에 남은 URL 수', v: s.pending_urls ?? 0 },
    { k: 'repeated_lists', label: '반복 목록 차단', desc: '같은 상세 링크 집합을 반복한 목록 분기', v: s.repeated_lists ?? 0 },
    { k: 'removed', label: '삭제', desc: '기존 색인에서 지운 페이지', v: s.removed ?? 0, accent: 'mute' },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
      {items.map((i) => (
        <div key={i.k} className="border border-border rounded-md px-3 py-2" title={i.k}>
          <div className="text-xs font-medium text-ink">{i.label}</div>
          <div
            className={`text-lg font-semibold tabular-nums ${
              i.accent === 'good' ? 'text-primary' : i.accent === 'mute' ? 'text-ink-muted' : 'text-ink'
            }`}
          >
            {i.v}
          </div>
          <div className="mt-0.5 text-[11px] text-ink-muted leading-tight">{i.desc}</div>
        </div>
      ))}
    </div>
  );
}
