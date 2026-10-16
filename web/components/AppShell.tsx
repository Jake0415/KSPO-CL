'use client';

import type { ReactNode } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import {
  Activity, Bell, ChevronRight, Clock, Database, Globe, Home, LayoutList,
  LogOut, Search, Settings,
} from 'lucide-react';
import { useBoardSources } from '@/api/boardSources';
import { apiFetch } from '@/lib/api';
import { useLogout } from '@/lib/session';

type NavItem = {
  key: string;
  label: string;
  icon: typeof Home;
  to: string;
  count?: number;
};

const NAV: NavItem[] = [
  { key: 'dashboard',     label: '대시보드',     icon: Home,          to: '/' },
  { key: 'sites',         label: '사이트 탐색',   icon: Globe,         to: '/sites' },
  { key: 'domains',       label: '데이터 소스',   icon: Database,      to: '/domains' },
  { key: 'board-sources', label: '게시판 소스',   icon: LayoutList,    to: '/board-sources' },
  { key: 'jobs',          label: '크롤 모니터',   icon: Activity,      to: '/jobs' },
  { key: 'pages',         label: '문서 탐색',     icon: Clock,         to: '/pages' },
];

const NAV_ADMIN: NavItem[] = [
  { key: 'settings', label: '설정', icon: Settings, to: '/settings' },
];

type Props = {
  title: string;
  subtitle?: string;
  breadcrumbs?: string[];
  actions?: ReactNode;
  children: ReactNode;
};

export function AppShell({ title, subtitle, breadcrumbs = [], actions, children }: Props) {
  const pathname = usePathname() ?? '/';
  const router = useRouter();
  const { data: candidateSources } = useBoardSources('candidate');
  const candidateCount = candidateSources?.length;

  const navWithCounts = NAV.map((n) =>
    n.key === 'board-sources' ? { ...n, count: candidateCount } : n,
  );

  const { data: me } = useQuery({
    queryKey: ['session'],
    queryFn: () => apiFetch<{ username: string; via: string }>('/api/auth/me'),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });
  const logout = useLogout();

  async function onLogout() {
    try {
      await logout.mutateAsync();
    } finally {
      router.replace('/login');
    }
  }

  const isActive = (to: string): boolean => {
    if (to === '/') return pathname === '/';
    return pathname.startsWith(to);
  };

  return (
    <div className="min-h-screen flex bg-bg">
      {/* Sidebar */}
      <aside className="w-[248px] bg-surface border-r border-border flex flex-col shrink-0">
        <div className="h-14 px-4 flex items-center gap-2.5 border-b border-border">
          <div className="w-8 h-8 rounded-lg bg-primary grid place-items-center text-white font-bold text-sm">
            k
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight">kspo-ingest</div>
            <div className="text-[11px] text-ink-muted">운영 콘솔</div>
          </div>
        </div>

        <nav className="flex-1 p-3 flex flex-col gap-0.5">
          <div className="px-2 py-2 text-[11px] font-medium uppercase tracking-wider text-ink-muted">
            메뉴
          </div>
          {navWithCounts.map((n) => (
            <NavLinkItem key={n.key} item={n} active={isActive(n.to)} onClick={() => router.push(n.to)} />
          ))}

          <div className="px-2 py-2 mt-4 text-[11px] font-medium uppercase tracking-wider text-ink-muted">
            관리
          </div>
          {NAV_ADMIN.map((n) => (
            <NavLinkItem key={n.key} item={n} active={isActive(n.to)} onClick={() => router.push(n.to)} />
          ))}
        </nav>

        <div className="p-3 border-t border-border flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-full bg-primary text-white grid place-items-center text-xs font-bold">
            {me?.username?.[0]?.toUpperCase() ?? '관'}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium truncate">{me?.username ?? '관리자'}</div>
            <div className="text-[11px] text-ink-muted">Admin</div>
          </div>
          <button
            onClick={onLogout}
            className="h-8 w-8 grid place-items-center rounded-md hover:bg-bg-muted text-ink-muted"
            title="로그아웃"
            aria-label="로그아웃"
          >
            <LogOut size={16} />
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Topbar */}
        <header className="h-14 px-6 border-b border-border bg-surface flex items-center justify-between">
          <nav className="flex items-center gap-1.5 text-sm text-ink-muted">
            {breadcrumbs.map((b, i) => (
              <span key={`${b}-${i}`} className="flex items-center gap-1.5">
                {i > 0 && <ChevronRight size={14} />}
                <span className={i === breadcrumbs.length - 1 ? 'text-ink font-medium' : ''}>{b}</span>
              </span>
            ))}
          </nav>
          <div className="flex items-center gap-1">
            <button className="h-8 w-8 grid place-items-center rounded-md hover:bg-bg-muted" aria-label="search">
              <Search size={16} />
            </button>
            <button className="h-8 w-8 grid place-items-center rounded-md hover:bg-bg-muted" aria-label="notifications">
              <Bell size={16} />
            </button>
          </div>
        </header>

        {/* Page header */}
        <div className="px-8 pt-8 pb-6 max-w-[1280px] w-full">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight font-display">{title}</h1>
              {subtitle && <p className="mt-1.5 text-sm text-ink-muted">{subtitle}</p>}
            </div>
            {actions && <div className="flex items-center gap-2">{actions}</div>}
          </div>
        </div>

        {/* Content */}
        <main className="flex-1 px-8 pb-12 max-w-[1280px] w-full">{children}</main>
      </div>
    </div>
  );
}

type NavLinkItemProps = {
  item: NavItem;
  active: boolean;
  onClick: () => void;
};

function NavLinkItem({ item, active, onClick }: NavLinkItemProps) {
  const Icon = item.icon;
  return (
    <button
      onClick={onClick}
      className={`group relative flex items-center gap-2.5 px-3 h-9 rounded-lg text-[13px] font-medium transition-colors ${
        active ? 'bg-primary-soft text-primary' : 'text-ink hover:bg-bg-muted'
      }`}
    >
      {active && <span className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-full bg-primary" />}
      <Icon size={16} className={active ? 'text-primary' : 'text-ink-muted group-hover:text-ink'} />
      <span className="flex-1 text-left">{item.label}</span>
      {item.count != null && (
        <span className="text-[11px] font-medium px-1.5 py-0.5 rounded bg-bg-muted text-ink-muted">
          {item.count}
        </span>
      )}
    </button>
  );
}
