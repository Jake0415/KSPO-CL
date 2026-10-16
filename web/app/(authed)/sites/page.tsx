'use client';

import { useMemo, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { InfoTip } from '@/components/ui/InfoTip';
import { type SiteSummary, useSitesList, useSiteStructure } from '@/api/console';

type Filter = 'all' | 'active' | 'inactive';

function fmt(ts: string | null): string {
  return ts ? new Date(ts).toLocaleString('ko-KR') : '크롤 이력 없음';
}

// 상태 코드 → 쉬운 뜻 (hover 툴팁용)
const STATUS_MEANING: Record<string, string> = {
  INDEXED: '적재완료 — 챗봇이 실제로 사용하는 문서 (벡터DB 저장됨)',
  DROPPED: '제외 — 짧은 본문·오류·빈 페이지 등으로 학습 제외',
  DISCOVERED: '발견 — 링크는 찾았으나 아직 수집/처리 안 된 상태',
  FETCHED: '수집됨 — HTML을 받아온 직후 (정제 전)',
  CLEANED: '정제됨 — 본문 추출 완료 (임베딩 전)',
  REFINED: '정제완료 — LLM 정제까지 끝난 상태',
  ERROR: '오류 — 접속/추출 실패 (SSL·404·타임아웃 등)',
  REMOVED: '삭제 — 원본에서 사라져 지식DB에서 제거된 문서',
};

export default function SiteExplorerPage() {
  const { data: sites, isLoading, isError } = useSitesList();
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [selected, setSelected] = useState<number | undefined>(undefined);

  const rows = useMemo(() => {
    let list = sites ?? [];
    if (filter === 'active') list = list.filter((d) => d.is_active);
    if (filter === 'inactive') list = list.filter((d) => !d.is_active);
    if (q.trim()) list = list.filter((d) => d.host.toLowerCase().includes(q.toLowerCase()));
    return list;
  }, [sites, filter, q]);

  const sel = selected ?? rows[0]?.domain_id;

  return (
    <AppShell
      title="Site Explorer"
      subtitle="등록 사이트 · 실 적재·최근크롤·실제 스케줄"
      breadcrumbs={['홈', '사이트']}
    >
      <div className="grid grid-cols-1 lg:grid-cols-[400px_1fr] gap-4">
        <Card>
          <CardBody className="space-y-3">
            <Input
              data-testid="site-search"
              placeholder="호스트 검색"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <div className="flex items-center gap-2">
              {(['all', 'active', 'inactive'] as Filter[]).map((f) => (
                <button
                  key={f}
                  data-testid={`site-filter-${f}`}
                  onClick={() => setFilter(f)}
                  className={`text-xs px-2.5 h-7 rounded-md ${
                    filter === f ? 'bg-primary text-white' : 'bg-bg-muted text-ink hover:bg-surface-hover'
                  }`}
                >
                  {f === 'all' ? '전체' : f === 'active' ? '활성' : '비활성'}
                </button>
              ))}
            </div>
            {isLoading && <p className="text-sm text-ink-muted">불러오는 중…</p>}
            {isError && <p className="text-sm text-danger">사이트 목록 조회 실패</p>}
            <div className="text-[11px] text-ink-muted flex items-center px-1">
              각 항목: 적재 / 수집 · 최근 크롤
              <InfoTip text="적재 = 챗봇이 학습한 문서 수(벡터DB 저장), 수집 = 크롤한 전체 페이지 수. 예: 147/227 = 227개 크롤 중 147개를 챗봇이 사용." />
            </div>
            <div className="space-y-1 max-h-[65vh] overflow-auto" data-testid="site-list">
              {rows.map((d: SiteSummary) => (
                <button
                  key={d.domain_id}
                  onClick={() => setSelected(d.domain_id)}
                  className={`w-full text-left px-3 py-2 rounded-md text-sm ${
                    sel === d.domain_id ? 'bg-primary/10 border border-primary/30' : 'hover:bg-bg-muted border border-transparent'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium truncate">{d.host}</span>
                    <Badge variant={d.is_active ? 'success' : 'muted'}>
                      {d.is_active ? '활성' : '비활성'}
                    </Badge>
                  </div>
                  <div className="text-[11px] text-ink-muted mt-0.5 tabular-nums">
                    적재 {d.indexed.toLocaleString()} / {d.total.toLocaleString()} · 최근 {fmt(d.last_crawl_at)}
                  </div>
                </button>
              ))}
              {rows.length === 0 && !isLoading && (
                <p className="text-sm text-ink-muted px-3 py-4">결과 없음</p>
              )}
            </div>
          </CardBody>
        </Card>

        <SiteStructurePanel domainId={sel} />
      </div>
    </AppShell>
  );
}

function SiteStructurePanel({ domainId }: { domainId?: number }) {
  const { data, isLoading } = useSiteStructure(domainId);
  if (!domainId) return <Card><CardBody><p className="text-sm text-ink-muted">사이트를 선택하세요.</p></CardBody></Card>;
  if (isLoading || !data) return <Card><CardBody><p className="text-sm text-ink-muted">구조 로딩 중…</p></CardBody></Card>;

  const maxPattern = Math.max(1, ...data.url_patterns.map((u) => u.count));

  return (
    <div className="space-y-4" data-testid="site-structure">
      <Card>
        <CardHeader title={data.host} description={`총 ${data.total_pages.toLocaleString()} 페이지`} />
        <CardBody className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <Stat k="상태" v={data.is_active ? '활성' : '비활성'} tip="크롤 ON/OFF — 자동 크롤 대상 여부" />
          <Stat
            k="max depth"
            v={String(data.max_depth)}
            tip="최대 탐색 깊이 — 시작 페이지에서 링크를 몇 단계까지 따라갈지 (예: 2 = 홈→목록→상세)"
          />
          <Stat
            k="max pages"
            v={data.max_pages.toLocaleString()}
            tip="최대 수집 수 — 한 번의 크롤에서 처리할 페이지 상한"
          />
          <Stat k="최근 크롤" v={fmt(data.last_crawl_at)} tip="마지막으로 이 사이트 크롤이 끝난 시각" />
          <Stat
            k="실제 스케줄"
            v={data.schedule}
            wide
            tip="자동 크롤 주기 — 실제 운영 크론 기준. 활성 도메인은 매월 1일 02:00 전체크롤, 게시판 등록 시 매일 04:00 추가."
          />
          <Stat
            k="게시판 소스"
            v={`${data.board_source_count}건`}
            tip="등록 게시판 수 — 이 사이트에서 매일 증분 크롤하는 게시판(confirmed) 개수"
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center">
              크롤 커버리지 (상태별)
              <InfoTip text="수집 처리 현황 — 각 페이지가 어느 단계까지 처리됐는지. 상태 코드에 마우스를 올리면 뜻이 나옵니다." />
            </span>
          }
        />
        <CardBody className="flex flex-wrap gap-2">
          {data.by_status.map((u) => (
            <div
              key={u.key}
              className="px-3 py-1.5 rounded-md bg-bg-muted text-xs flex items-center"
              title={STATUS_MEANING[u.key] ?? u.key}
            >
              <span className="text-ink-muted">{u.key}</span>{' '}
              <span className="font-semibold tabular-nums ml-1">{u.count.toLocaleString()}</span>
              {STATUS_MEANING[u.key] && <InfoTip text={STATUS_MEANING[u.key]} />}
            </div>
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center">
              크롤 깊이 분포
              <InfoTip text="링크 단계별 분포 — 시작 페이지(0단계)에서 링크를 몇 번 따라간 페이지인지. 1단계 = 홈에서 1클릭." />
            </span>
          }
        />
        <CardBody className="flex flex-wrap gap-2">
          {data.by_depth.map((u) => (
            <div
              key={u.key}
              className="px-3 py-1.5 rounded-md bg-bg-muted text-xs"
              title={`${u.key.replace('depth ', '')}단계 — 시작 페이지에서 링크 ${u.key.replace('depth ', '')}번 따라간 페이지`}
            >
              <span className="text-ink-muted">{u.key}</span>{' '}
              <span className="font-semibold tabular-nums">{u.count.toLocaleString()}</span>
            </div>
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center">
              콘텐츠 유닛 / URL 패턴
              <InfoTip text="페이지 종류(경로별) — 주소의 경로 조각으로 페이지를 묶은 것. 예: 'bbs 831' = 주소에 /bbs/가 든 게시판 페이지가 831개." />
            </span>
          }
          description="path 세그먼트별 페이지 수"
        />
        <CardBody className="space-y-1.5">
          {data.url_patterns.map((u) => (
            <div key={u.key} className="flex items-center gap-2">
              <span className="w-40 text-xs font-mono truncate shrink-0">{u.key}</span>
              <div className="flex-1 h-4 bg-bg-muted rounded overflow-hidden">
                <div
                  className="h-full bg-primary/60"
                  style={{ width: `${(u.count / maxPattern) * 100}%` }}
                />
              </div>
              <span className="w-16 text-right text-xs tabular-nums">{u.count.toLocaleString()}</span>
            </div>
          ))}
          {data.url_patterns.length === 0 && <p className="text-sm text-ink-muted">패턴 없음</p>}
        </CardBody>
      </Card>
    </div>
  );
}

function Stat({ k, v, tip, wide }: { k: string; v: string; tip?: string; wide?: boolean }) {
  return (
    <div className={`rounded-md bg-bg-muted p-2.5 ${wide ? 'col-span-2' : ''}`}>
      <div className="text-[11px] text-ink-muted flex items-center">
        {k}
        {tip && <InfoTip text={tip} />}
      </div>
      <div className="font-semibold mt-0.5 text-sm">{v}</div>
    </div>
  );
}
