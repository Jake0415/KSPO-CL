// StatusPill — 실시간 상태 표시
// 운영 콘솔 곳곳에서 사용. running 상태는 펄스 애니메이션.

import { CheckCircle2, XCircle, Pause, Clock } from "lucide-react";

const VARIANTS = {
  running: { label: "실행 중", color: "var(--success)", pulse: true,  bg: "var(--success-soft)" },
  success: { label: "성공",    color: "var(--success)", pulse: false, bg: "var(--success-soft)" },
  failed:  { label: "실패",    color: "var(--danger)",  pulse: false, bg: "var(--danger-soft)" },
  paused:  { label: "일시정지", color: "var(--warning)", pulse: false, bg: "var(--warning-soft)" },
  pending: { label: "대기",    color: "var(--ink-muted)", pulse: false, bg: "var(--bg-muted)" },
};

export function StatusPill({ status, label }) {
  const v = VARIANTS[status] ?? VARIANTS.pending;
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 h-6 rounded-full text-xs font-medium"
      style={{ background: v.bg, color: v.color }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{
          background: "currentColor",
          animation: v.pulse ? "pulse-dot 1.6s infinite" : undefined,
          boxShadow: v.pulse ? `0 0 0 3px ${v.color}33` : undefined,
        }}
      />
      {label ?? v.label}
    </span>
  );
}
