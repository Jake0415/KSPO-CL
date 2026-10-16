// AppShell — kspo-ingest 디자인 시스템 표준 페이지 골격
// React + Tailwind 기준 예제. 실제 프로젝트에서 그대로 복사해 사용.

import { ChevronRight, Home, Database, Activity, Clock, Users, Settings, Search, Bell, ChevronsLeft } from "lucide-react";

const NAV = [
  { key: "dashboard",  label: "대시보드",   icon: Home },
  { key: "sources",    label: "데이터 소스", icon: Database, count: 24 },
  { key: "monitoring", label: "모니터링",   icon: Activity },
  { key: "logs",       label: "실행 이력",   icon: Clock },
];

const NAV_ADMIN = [
  { key: "users",    label: "사용자/권한", icon: Users },
  { key: "settings", label: "설정",        icon: Settings },
];

export function AppShell({ title, subtitle, breadcrumbs = [], actions, children, currentRoute, onNavigate }) {
  return (
    <div className="min-h-screen flex bg-bg">
      {/* Sidebar */}
      <aside className="w-[248px] bg-surface border-r border-border flex flex-col shrink-0">
        <div className="h-14 px-4 flex items-center gap-2.5 border-b border-border">
          <div className="w-8 h-8 rounded-lg bg-primary grid place-items-center text-white font-bold text-sm">k</div>
          <div>
            <div className="text-sm font-semibold tracking-tight">kspo-ingest</div>
            <div className="text-[11px] text-ink-muted">운영 콘솔</div>
          </div>
        </div>

        <nav className="flex-1 p-3 flex flex-col gap-0.5">
          <div className="px-2 py-2 text-[11px] font-medium uppercase tracking-wider text-ink-muted">메뉴</div>
          {NAV.map((n) => <NavItem key={n.key} item={n} active={currentRoute === n.key} onClick={() => onNavigate(n.key)} />)}

          <div className="px-2 py-2 mt-4 text-[11px] font-medium uppercase tracking-wider text-ink-muted">관리</div>
          {NAV_ADMIN.map((n) => <NavItem key={n.key} item={n} active={currentRoute === n.key} onClick={() => onNavigate(n.key)} />)}
        </nav>

        <div className="p-3 border-t border-border flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-full bg-primary text-white grid place-items-center text-xs font-bold">김운</div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium truncate">김운영</div>
            <div className="text-[11px] text-ink-muted">Admin</div>
          </div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Topbar */}
        <header className="h-14 px-6 border-b border-border bg-surface flex items-center justify-between">
          <nav className="flex items-center gap-1.5 text-sm text-ink-muted">
            {breadcrumbs.map((b, i) => (
              <span key={i} className="flex items-center gap-1.5">
                {i > 0 && <ChevronRight size={14} />}
                <span className={i === breadcrumbs.length - 1 ? "text-ink font-medium" : ""}>{b}</span>
              </span>
            ))}
          </nav>
          <div className="flex items-center gap-1">
            <button className="btn btn-ghost btn-sm btn-icon"><Search size={16} /></button>
            <button className="btn btn-ghost btn-sm btn-icon"><Bell size={16} /></button>
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
        <main className="flex-1 px-8 pb-12 max-w-[1280px] w-full">
          {children}
        </main>
      </div>
    </div>
  );
}

function NavItem({ item, active, onClick }) {
  const Icon = item.icon;
  return (
    <button
      onClick={onClick}
      className={`group relative flex items-center gap-2.5 px-3 h-9 rounded-lg text-[13px] font-medium transition-colors
        ${active
          ? "bg-primary-soft text-primary"
          : "text-ink hover:bg-bg-muted"
        }`}
    >
      {active && <span className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-full bg-primary" />}
      <Icon size={16} className={active ? "text-primary" : "text-ink-muted group-hover:text-ink"} />
      <span className="flex-1 text-left">{item.label}</span>
      {item.count != null && (
        <span className="text-[11px] font-medium px-1.5 py-0.5 rounded bg-bg-muted text-ink-muted">
          {item.count}
        </span>
      )}
    </button>
  );
}
