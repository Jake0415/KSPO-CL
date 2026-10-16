'use client';

import { type FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AppShell } from '@/components/AppShell';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Checkbox } from '@/components/ui/Checkbox';
import { Input, Textarea } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import { useCreateDomain, type DomainCreate } from '@/api/domains';

const splitLines = (s: string): string[] | null =>
  s.trim() ? s.split('\n').map((l) => l.trim()).filter(Boolean) : null;

export default function DomainNewPage() {
  const router = useRouter();
  const { push } = useToast();
  const create = useCreateDomain();

  const [host, setHost] = useState('');
  const [scheme, setScheme] = useState<'http' | 'https'>('https');
  const [displayName, setDisplayName] = useState('');
  const [maxDepth, setMaxDepth] = useState(10);
  const [maxPages, setMaxPages] = useState(2_000);
  const [rateLimitRps, setRateLimitRps] = useState('1.5');
  const [concurrency, setConcurrency] = useState(4);
  const [usePlaywright, setUsePlaywright] = useState(false);
  const [respectRobots, setRespectRobots] = useState(true);
  const [userAgent, setUserAgent] = useState('');
  const [allowPatterns, setAllowPatterns] = useState('');
  const [denyPatterns, setDenyPatterns] = useState('');
  const [selectorBlacklist, setSelectorBlacklist] = useState('');
  const [incrementalCron, setIncrementalCron] = useState('0 3 * * 0');
  const [incrementalEnabled, setIncrementalEnabled] = useState(true);
  const [hostError, setHostError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setHostError(null);

    const body: DomainCreate = {
      host,
      scheme,
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
      is_active: true,
    } as DomainCreate;

    try {
      const created = await create.mutateAsync(body);
      push({ kind: 'success', msg: `도메인 ${created.host} 등록됨` });
      router.replace(`/domains/${created.id}`);
    } catch (e) {
      const msg = (e as Error).message;
      if (msg.includes('409')) setHostError('이미 등록된 호스트입니다.');
      else if (msg.includes('422')) setHostError('입력값을 다시 확인해 주세요.');
      else push({ kind: 'error', msg: '도메인 등록에 실패했습니다.' });
    }
  }

  return (
    <AppShell title="새 도메인" breadcrumbs={['홈', '데이터 소스', '새 도메인']}>
      <form onSubmit={submit} className="space-y-6 max-w-form">
        <Card>
          <CardHeader title="기본" />
          <CardBody className="space-y-4">
            <Input
              label="호스트 (필수)"
              placeholder="www.kspo.or.kr"
              value={host}
              onChange={(e) => setHost(e.target.value)}
              error={hostError ?? undefined}
              required
            />
            <div className="grid grid-cols-2 gap-4">
              <label className="block">
                <span className="block text-sm font-medium mb-1.5">스키마</span>
                <select
                  value={scheme}
                  onChange={(e) => setScheme(e.target.value as 'http' | 'https')}
                  className="w-full h-control-lg px-3 rounded-md border border-border bg-surface"
                >
                  <option value="https">https</option>
                  <option value="http">http</option>
                </select>
              </label>
              <Input
                label="표시명"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="크롤 한도" />
          <CardBody className="grid grid-cols-2 gap-4">
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
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="옵션" />
          <CardBody className="space-y-4">
            <Checkbox
              label="Playwright 사용 (동적 렌더링 페이지)"
              checked={usePlaywright}
              onChange={(e) => setUsePlaywright(e.target.checked)}
            />
            <Checkbox
              label="robots.txt 준수"
              checked={respectRobots}
              onChange={(e) => setRespectRobots(e.target.checked)}
            />
            <Input
              label="User-Agent 오버라이드 (비우면 기본값 사용)"
              value={userAgent}
              onChange={(e) => setUserAgent(e.target.value)}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="패턴" description="1줄 = 1 패턴. 비워두면 적용 안 함." />
          <CardBody className="space-y-4">
            <Textarea
              label="허용 패턴 (allow_patterns)"
              value={allowPatterns}
              onChange={(e) => setAllowPatterns(e.target.value)}
            />
            <Textarea
              label="차단 패턴 (deny_patterns)"
              value={denyPatterns}
              onChange={(e) => setDenyPatterns(e.target.value)}
            />
            <Textarea
              label="셀렉터 블랙리스트 (selector_blacklist)"
              hint="CSS 셀렉터. 예: .gnb, footer, #hd"
              value={selectorBlacklist}
              onChange={(e) => setSelectorBlacklist(e.target.value)}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="증분" description="기본: 매주 일요일 03:00 KST." />
          <CardBody className="space-y-4">
            <Input
              label="cron 표현식"
              hint="예: 0 3 * * 0 (매주 일요일 03:00)"
              value={incrementalCron}
              onChange={(e) => setIncrementalCron(e.target.value)}
            />
            <Checkbox
              label="증분 활성화"
              checked={incrementalEnabled}
              onChange={(e) => setIncrementalEnabled(e.target.checked)}
            />
          </CardBody>
        </Card>

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => router.push('/domains')}>
            취소
          </Button>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            {create.isPending ? '저장 중…' : '저장'}
          </Button>
        </div>
      </form>
    </AppShell>
  );
}
