'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Trash2 } from 'lucide-react';
import { AppShell } from '@/components/AppShell';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Checkbox } from '@/components/ui/Checkbox';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { Input, Textarea } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import {
  type Domain,
  type DomainUpdate,
  useDeleteDomain,
  useDomain,
  useUpdateDomain,
} from '@/api/domains';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/Table';
import { useBoardSources } from '@/api/boardSources';

const joinLines = (arr: string[] | null): string => (arr ? arr.join('\n') : '');
const splitLines = (s: string): string[] | null =>
  s.trim() ? s.split('\n').map((l) => l.trim()).filter(Boolean) : null;

export default function DomainDetailPage() {
  const params = useParams<{ id: string }>();
  const did = params?.id ? Number(params.id) : undefined;
  const { data, isLoading, isError } = useDomain(did);

  if (isLoading) {
    return <Skeleton text="도메인 정보를 불러오는 중…" />;
  }
  if (isError || !data || did === undefined) {
    return <Skeleton text="도메인을 찾을 수 없습니다." />;
  }
  return <Loaded domain={data} id={did} />;
}

function Skeleton({ text }: { text: string }) {
  return (
    <AppShell title="도메인 상세" breadcrumbs={['홈', '데이터 소스', '상세']}>
      <Card>
        <CardBody>
          <p className="text-sm text-ink-muted">{text}</p>
        </CardBody>
      </Card>
    </AppShell>
  );
}

function Loaded({ domain, id }: { domain: Domain; id: number }) {
  const router = useRouter();
  const { push } = useToast();
  const update = useUpdateDomain(id);
  const del = useDeleteDomain();

  const [startUrl, setStartUrl] = useState(domain.start_url ?? '');
  const [displayName, setDisplayName] = useState(domain.display_name ?? '');
  const [maxDepth, setMaxDepth] = useState(domain.max_depth);
  const [maxPages, setMaxPages] = useState(domain.max_pages);
  const [rateLimitRps, setRateLimitRps] = useState(String(domain.rate_limit_rps));
  const [concurrency, setConcurrency] = useState(domain.concurrency);
  const [usePlaywright, setUsePlaywright] = useState(domain.use_playwright);
  const [respectRobots, setRespectRobots] = useState(domain.respect_robots);
  const [userAgent, setUserAgent] = useState(domain.user_agent ?? '');
  const [allowPatterns, setAllowPatterns] = useState(joinLines(domain.allow_patterns));
  const [denyPatterns, setDenyPatterns] = useState(joinLines(domain.deny_patterns));
  const [selectorBlacklist, setSelectorBlacklist] = useState(joinLines(domain.selector_blacklist));
  const [incrementalCron, setIncrementalCron] = useState(domain.incremental_cron ?? '');
  const [incrementalEnabled, setIncrementalEnabled] = useState(domain.incremental_enabled ?? true);
  const [isActive, setIsActive] = useState(domain.is_active);
  const [confirmOpen, setConfirmOpen] = useState(false);

  async function save() {
    const body: DomainUpdate = {
      start_url: startUrl.trim() || null,
      display_name: displayName || null,
      max_depth: maxDepth,
      max_pages: maxPages,
      rate_limit_rps: rateLimitRps,
      concurrency,
      use_playwright: usePlaywright,
      respect_robots: respectRobots,
      user_agent: userAgent || null,
      allow_patterns: splitLines(allowPatterns),
      deny_patterns: splitLines(denyPatterns),
      selector_blacklist: splitLines(selectorBlacklist),
      incremental_cron: incrementalCron || null,
      incremental_enabled: incrementalEnabled,
      is_active: isActive,
    };
    try {
      await update.mutateAsync(body);
      push({ kind: 'success', msg: '저장됨' });
    } catch {
      push({ kind: 'error', msg: '저장에 실패했습니다.' });
    }
  }

  async function performDelete() {
    try {
      await del.mutateAsync(id);
      push({ kind: 'success', msg: `${domain.host} 삭제됨` });
      router.replace('/domains');
    } catch {
      push({ kind: 'error', msg: '삭제에 실패했습니다.' });
    }
  }

  return (
    <AppShell
      title={domain.host}
      subtitle={domain.display_name ?? undefined}
      breadcrumbs={['홈', '데이터 소스', domain.host]}
      actions={
        <Badge variant={domain.is_active ? 'success' : 'muted'}>
          {domain.is_active ? '활성' : '비활성'}
        </Badge>
      }
    >
      <div className="space-y-6 max-w-form">
        <Card>
          <CardHeader title="메타" />
          <CardBody className="text-sm text-ink-muted space-y-1">
            <div>도메인 ID: <span className="font-mono text-ink">{domain.id}</span></div>
            <div>등록일: <span className="text-ink">{domain.created_at}</span></div>
            <div>수정일: <span className="text-ink">{domain.updated_at}</span></div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="정보 수정" />
          <CardBody className="space-y-4">
            <Input label="기본 시작 URL" placeholder={`https://${domain.host}/`} value={startUrl} onChange={(e) => setStartUrl(e.target.value)} />
            <Input
              label="표시명"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="최대 깊이"
                type="number"
                min={0}
                max={50}
                value={maxDepth}
                onChange={(e) => setMaxDepth(Number(e.target.value))}
              />
              <Input
                label="최대 페이지"
                type="number"
                min={1}
                max={1_000_000}
                value={maxPages}
                onChange={(e) => setMaxPages(Number(e.target.value))}
              />
              <Input
                label="RPS (요청/초)"
                type="number"
                step="0.1"
                min="0.1"
                max="20"
                value={rateLimitRps}
                onChange={(e) => setRateLimitRps(e.target.value)}
              />
              <Input
                label="동시성"
                type="number"
                min={1}
                max={32}
                value={concurrency}
                onChange={(e) => setConcurrency(Number(e.target.value))}
              />
            </div>
            <Checkbox
              label="Playwright 사용"
              checked={usePlaywright}
              onChange={(e) => setUsePlaywright(e.target.checked)}
            />
            <Checkbox
              label="robots.txt 준수"
              checked={respectRobots}
              onChange={(e) => setRespectRobots(e.target.checked)}
            />
            <Input
              label="User-Agent"
              value={userAgent}
              onChange={(e) => setUserAgent(e.target.value)}
            />
            <Textarea
              label="허용 패턴"
              value={allowPatterns}
              onChange={(e) => setAllowPatterns(e.target.value)}
            />
            <Textarea
              label="차단 패턴"
              value={denyPatterns}
              onChange={(e) => setDenyPatterns(e.target.value)}
            />
            <Textarea
              label="셀렉터 블랙리스트"
              value={selectorBlacklist}
              onChange={(e) => setSelectorBlacklist(e.target.value)}
            />
            <Input
              label="증분 cron"
              value={incrementalCron}
              onChange={(e) => setIncrementalCron(e.target.value)}
            />
            <Checkbox
              label="증분 활성화"
              checked={incrementalEnabled}
              onChange={(e) => setIncrementalEnabled(e.target.checked)}
            />
            <Checkbox
              label="도메인 활성"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
            />
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="primary" onClick={save} disabled={update.isPending}>
                {update.isPending ? '저장 중…' : '저장'}
              </Button>
            </div>
          </CardBody>
        </Card>

        <Card className="border-danger/30">
          <CardHeader
            title="위험 영역"
            description="도메인을 삭제하면 모든 페이지·청크·첨부가 함께 삭제됩니다."
          />
          <CardBody>
            <Button variant="destructive" onClick={() => setConfirmOpen(true)}>
              <Trash2 size={16} /> 도메인 삭제
            </Button>
          </CardBody>
        </Card>

        <DomainBoardSources domainId={id} />
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`'${domain.host}' 삭제`}
        description="이 작업은 되돌릴 수 없습니다. 도메인과 모든 페이지·청크·첨부가 영구 삭제됩니다."
        confirmText="삭제"
        requireMatch={domain.host}
        onConfirm={() => {
          setConfirmOpen(false);
          void performDelete();
        }}
      />
    </AppShell>
  );
}

function DomainBoardSources({ domainId }: { domainId: number }) {
  const { data, isLoading } = useBoardSources();
  const sources = data?.filter((s) => s.domain_id === domainId) ?? [];

  const STATUS_LABELS: Record<string, string> = {
    candidate: '후보',
    confirmed: '승인',
    rejected: '거부',
  };

  return (
    <Card>
      <CardHeader title="게시판 소스" />
      <CardBody className="px-0 py-0">
        {isLoading && (
          <div className="px-6 py-8 text-sm text-ink-muted">불러오는 중…</div>
        )}
        {!isLoading && sources.length === 0 && (
          <div className="px-6 py-8 text-sm text-ink-muted">등록된 게시판 소스가 없습니다.</div>
        )}
        {sources.length > 0 && (
          <Table>
            <THead>
              <TR>
                <TH>목록 URL</TH>
                <TH>상태</TH>
                <TH>탐지일</TH>
                <TH>마지막 갱신</TH>
              </TR>
            </THead>
            <TBody>
              {sources.map((src) => (
                <TR key={src.id}>
                  <TD className="font-medium max-w-xs truncate" title={src.list_url}>
                    {src.list_url}
                  </TD>
                  <TD>
                    <Badge
                      variant={
                        src.status === 'confirmed'
                          ? 'success'
                          : src.status === 'candidate'
                            ? 'warning'
                            : 'muted'
                      }
                    >
                      {STATUS_LABELS[src.status] ?? src.status}
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
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </CardBody>
    </Card>
  );
}
