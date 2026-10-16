'use client';

import { useQuery } from '@tanstack/react-query';
import { AppShell } from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { InfoTip } from '@/components/ui/InfoTip';
import { STATUS_MEANING, TERM } from '@/lib/terms';
import { useOverview } from '@/api/console';

type Kpi = {
  domain_id: number | null;
  measured_at: string;
  coverage_pct: string;
  avg_freshness_days: string | null;
  job_success_rate_pct: string;
  monthly_cost_krw: string;
  indexed_count: number;
  dropped_count: number;
  error_count: number;
  snapshot: boolean;
};

export default function DashboardPage() {
  const { data: kpi } = useQuery({
    queryKey: ['kpi', 'latest'],
    queryFn: () => apiFetch<Kpi>('/api/kpi/latest'),
    refetchInterval: 30_000,
  });
  const { data: ov, isLoading, isError } = useOverview();

  return (
    <AppShell
      title="Executive Dashboard"
      subtitle="RAG 파이프라인 전체 상태"
      breadcrumbs={['홈', '대시보드']}
    >
      {isLoading && <SkeletonGrid />}
      {isError && (
        <div className="bg-surface border border-danger/30 text-danger rounded-lg p-4 text-sm">
          Overview 로드 실패. /api/console/overview 확인 필요.
        </div>
      )}
      {ov && (
        <div className="space-y-6" data-testid="dashboard">
          {/* System health banner */}
          <div className="flex items-center gap-3">
            <Badge variant={ov.system_health === 'healthy' ? 'success' : 'danger'}>
              시스템 {ov.system_health === 'healthy' ? '정상' : '주의'}
            </Badge>
            <Badge variant={ov.crawl_health_pct >= 90 ? 'success' : ov.crawl_health_pct >= 70 ? 'warning' : 'danger'}>
              크롤 헬스 {ov.crawl_health_pct}%
            </Badge>
            <InfoTip text={TERM.crawlHealth} />
            {ov.running_crawls > 0 && <Badge variant="info">실행중 {ov.running_crawls}</Badge>}
            {ov.failed_crawls > 0 && <Badge variant="warning">실패 {ov.failed_crawls}</Badge>}
          </div>

          {/* Core counts */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4" data-testid="stat-cards">
            <Stat label="전체 사이트" value={ov.sites_total} sub={`활성 ${ov.sites_active}`} tip="등록된 크롤 대상 사이트 수 (활성 = 자동 크롤 ON)" />
            <Stat label="문서" value={ov.docs_total} sub={`INDEXED ${ov.docs_by_status.INDEXED ?? 0}`} tip={TERM.docs} />
            <Stat label="청크" value={ov.chunks_total} tip={TERM.chunks} />
            <Stat label="임베딩(벡터)" value={ov.embeddings_total} tip={TERM.embeddings} />
            <Stat label="오늘 신규" value={ov.new_docs_today} variant="success" tip={TERM.newToday} />
            <Stat label="오늘 갱신" value={ov.updated_docs_today} variant="info" tip={TERM.updatedToday} />
          </div>

          {/* Doc status breakdown */}
          <Card>
            <CardHeader
              title={
                <span className="inline-flex items-center">
                  문서 상태 분포
                  <InfoTip text="각 문서가 처리 파이프라인의 어느 단계에 있는지. 상태 칩에 마우스를 올리면 뜻이 나옵니다." />
                </span>
              }
            />
            <CardBody className="flex flex-wrap gap-2">
              {Object.entries(ov.docs_by_status).map(([k, v]) => (
                <div
                  key={k}
                  className="px-3 py-1.5 rounded-md bg-bg-muted text-xs flex items-center"
                  title={STATUS_MEANING[k] ?? k}
                >
                  <span className="text-ink-muted">{k}</span>{' '}
                  <span className="font-semibold tabular-nums ml-1">{v.toLocaleString()}</span>
                  {STATUS_MEANING[k] && <InfoTip text={STATUS_MEANING[k]} />}
                </div>
              ))}
            </CardBody>
          </Card>

          {/* KPI targets (from existing /api/kpi) */}
          {kpi && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <KpiCard label="적재 커버리지" value={`${kpi.coverage_pct}%`} tip={TERM.coverage} />
              <KpiCard
                label="평균 신선도"
                value={kpi.avg_freshness_days != null ? `${kpi.avg_freshness_days}일` : '-'}
                tip={TERM.freshness}
              />
              <KpiCard label="Job 성공률(7일)" value={`${kpi.job_success_rate_pct}%`} tip={TERM.jobSuccess} />
              <KpiCard
                label="월 LLM 비용"
                value={`${Number(kpi.monthly_cost_krw).toLocaleString()}원`}
                tip={TERM.cost}
              />
            </div>
          )}

          <div className="text-xs text-ink-muted">
            최근 크롤: {ov.last_crawl_at ? new Date(ov.last_crawl_at).toLocaleString('ko-KR') : '-'}
            {' · '}최근 임베딩: {ov.last_embed_at ? new Date(ov.last_embed_at).toLocaleString('ko-KR') : '-'}
          </div>
        </div>
      )}
    </AppShell>
  );
}

function Stat({
  label,
  value,
  sub,
  variant,
  tip,
}: {
  label: string;
  value: number;
  sub?: string;
  variant?: 'success' | 'info';
  tip?: string;
}) {
  const color = variant === 'success' ? 'text-success' : variant === 'info' ? 'text-primary' : 'text-ink';
  return (
    <div className="bg-surface border border-border rounded-lg p-4">
      <div className="text-xs text-ink-muted flex items-center">
        {label}
        {tip && <InfoTip text={tip} />}
      </div>
      <div className={`mt-2 text-2xl font-semibold tabular-nums ${color}`}>{value.toLocaleString()}</div>
      {sub && <div className="mt-1 text-[11px] text-ink-muted">{sub}</div>}
    </div>
  );
}

function KpiCard({ label, value, tip }: { label: string; value: string; tip?: string }) {
  return (
    <div className="bg-surface border border-border rounded-lg p-4">
      <div className="text-xs text-ink-muted flex items-center">
        {label}
        {tip && <InfoTip text={tip} />}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums text-ink">{value}</div>
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="bg-surface border border-border rounded-lg p-4 h-[92px] animate-pulse" />
      ))}
    </div>
  );
}
