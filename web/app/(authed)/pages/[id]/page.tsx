'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { AppShell } from '@/components/AppShell';
import { Badge, type BadgeVariant } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/Table';
import { type PageStatus, usePage } from '@/api/pages';
import { usePageChunks } from '@/api/console';
import { InfoTip } from '@/components/ui/InfoTip';
import { STATUS_MEANING, TERM } from '@/lib/terms';

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

const TABS = ['메타', '추출본문', '청크', '첨부'] as const;
type Tab = (typeof TABS)[number];

export default function PageDetailPage() {
  const params = useParams<{ id: string }>();
  const pageId = params?.id ? Number(params.id) : undefined;
  const { data, isLoading, isError } = usePage(pageId);
  const { data: chunkTexts } = usePageChunks(pageId);
  const [tab, setTab] = useState<Tab>('메타');

  if (isLoading) {
    return (
      <AppShell title="페이지 상세" breadcrumbs={['홈', '페이지', '상세']}>
        <Card><CardBody><p className="text-sm text-ink-muted">불러오는 중…</p></CardBody></Card>
      </AppShell>
    );
  }
  if (isError || !data) {
    return (
      <AppShell title="페이지 상세" breadcrumbs={['홈', '페이지', '상세']}>
        <Card><CardBody><p className="text-sm text-ink-muted">페이지를 찾을 수 없습니다.</p></CardBody></Card>
      </AppShell>
    );
  }

  return (
    <AppShell
      title={data.title ?? `#${data.id}`}
      subtitle={data.url}
      breadcrumbs={['홈', '페이지', `#${data.id}`]}
      actions={
        <div className="flex items-center gap-2">
          <a
            href={data.url}
            target="_blank"
            rel="noreferrer"
            className="text-xs px-2.5 h-7 grid place-items-center rounded-md bg-bg-muted text-ink hover:bg-surface-hover"
          >
            원본 열기 ↗
          </a>
          <span className="inline-flex items-center" title={STATUS_MEANING[data.status] ?? data.status}>
            <Badge variant={STATUS_VARIANT[data.status]}>{data.status}</Badge>
            <InfoTip text={STATUS_MEANING[data.status] ?? data.status} />
          </span>
        </div>
      }
    >
      <div className="space-y-4 max-w-form" data-testid="page-detail">
        <div className="flex items-center gap-2 border-b border-border pb-2">
          {TABS.map((t) => (
            <button
              key={t}
              data-testid={`tab-${t}`}
              onClick={() => setTab(t)}
              className={`text-sm px-3 h-8 rounded-md ${
                tab === t ? 'bg-primary text-white' : 'text-ink hover:bg-bg-muted'
              }`}
            >
              {t}
              {t === '청크' && data.chunks.length > 0 && (
                <span className="ml-1 text-[10px] opacity-70">({data.chunks.length})</span>
              )}
              {t === '첨부' && data.attachments_count > 0 && (
                <span className="ml-1 text-[10px] opacity-70">({data.attachments_count})</span>
              )}
            </button>
          ))}
        </div>

        {tab === '메타' && (
          <Card>
            <CardHeader title="메타데이터" />
            <CardBody className="text-sm space-y-1.5">
              <Row k="ID" v={`#${data.id}`} />
              <Row k="도메인" v={`#${data.domain_id}`} />
              <Row k="URL (원본 추적)" v={data.url} mono />
              <Row k="url_hash" v={data.url_hash} mono />
              <Row k="제목" v={data.title ?? '-'} />
              <Row k="content_type" v={data.content_type ?? '-'} />
              <Row k="content_hash" v={data.content_hash ?? '-'} mono />
              <Row k="depth" v={String(data.depth)} />
              <Row k="http_status" v={data.http_status?.toString() ?? '-'} />
              <Row k="error_count" v={String(data.error_count)} />
              {data.drop_reason && <Row k="drop_reason" v={data.drop_reason} />}
              <Row k="discovered_at" v={new Date(data.discovered_at).toLocaleString('ko-KR')} />
              <Row
                k="last_fetched_at"
                v={data.last_fetched_at ? new Date(data.last_fetched_at).toLocaleString('ko-KR') : '-'}
              />
              <Row
                k="last_indexed_at"
                v={data.last_indexed_at ? new Date(data.last_indexed_at).toLocaleString('ko-KR') : '-'}
              />
            </CardBody>
          </Card>
        )}

        {tab === '추출본문' && (
          <Card>
            <CardHeader
              title={
                <span className="inline-flex items-center">
                  추출 본문 (벡터DB 저장 텍스트)
                  <InfoTip text={TERM.extracted} />
                </span>
              }
            />
            <CardBody>
              {!chunkTexts || chunkTexts.length === 0 ? (
                <Empty text="적재된 벡터 청크가 없습니다 (INDEXED 문서에만 존재)." />
              ) : (
                <div className="space-y-3" data-testid="extracted-content">
                  {chunkTexts.map((c, i) => (
                    <div key={c.point_id} className="rounded-md border border-border bg-bg-muted p-3">
                      <div className="text-[11px] text-ink-muted mb-1.5">
                        chunk {i + 1} · point {c.point_id.slice(0, 8)}…
                      </div>
                      <pre className="whitespace-pre-wrap break-words text-xs text-ink font-sans leading-relaxed">
                        {c.text}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>
        )}

        {tab === '청크' && (
          <Card>
            <CardBody className="px-0 py-0">
              {data.chunks.length === 0 ? (
                <Empty text="청크가 없습니다." />
              ) : (
                <Table>
                  <THead>
                    <TR>
                      <TH className="w-16">idx</TH>
                      <TH className="w-24 text-right tabular-nums">
                        tokens<InfoTip text={TERM.tokens} />
                      </TH>
                      <TH>모델</TH>
                      <TH className="w-28">embed<InfoTip text={TERM.embed} /></TH>
                      <TH className="w-28">kb<InfoTip text={TERM.kb} /></TH>
                      <TH className="w-20">첨부?</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {data.chunks.map((c) => (
                      <TR key={c.id}>
                        <TD className="font-medium tabular-nums">{c.chunk_index}</TD>
                        <TD className="text-right tabular-nums">{c.token_len}</TD>
                        <TD className="text-xs font-mono text-ink-muted">
                          {c.embedding_model ?? '-'}
                        </TD>
                        <TD>
                          <Badge variant={c.embed_status === 'OK' ? 'success' : 'warning'}>
                            {c.embed_status}
                          </Badge>
                        </TD>
                        <TD>
                          <Badge variant={c.kb_status === 'OK' ? 'success' : 'warning'}>
                            {c.kb_status}
                          </Badge>
                        </TD>
                        <TD className="text-ink-muted">
                          {c.is_attachment ? `att #${c.attachment_id}` : '-'}
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </CardBody>
          </Card>
        )}

        {tab === '첨부' && (
          <Card>
            <CardBody>
              <div className="text-sm text-ink-muted">
                첨부 메타 {data.attachments_count}건. (v2.0 Lite — 다운로드/추출 미수행, 챗봇은
                <code className="bg-bg-muted px-1.5 py-0.5 rounded text-xs ml-1">
                  /files/&#123;id&#125;
                </code>
                로 source_url 302 redirect)
              </div>
            </CardBody>
          </Card>
        )}
      </div>
    </AppShell>
  );
}

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex">
      <span className="w-36 text-ink-muted shrink-0">{k}</span>
      <span className={`break-all ${mono ? 'font-mono text-xs' : ''}`}>{v}</span>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="px-6 py-12 text-center text-sm text-ink-muted">{text}</div>;
}
