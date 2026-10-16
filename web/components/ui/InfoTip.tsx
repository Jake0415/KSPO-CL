'use client';

import { HelpCircle } from 'lucide-react';

/**
 * 용어 옆 `?` 아이콘 — hover 시 상세 의미(제안 용어 + 뜻)를 툴팁으로 표시.
 * 용어 자체는 그대로 두고 설명만 hover로 제공.
 */
export function InfoTip({ text, className = '' }: { text: string; className?: string }) {
  return (
    <span className={`relative inline-flex group align-middle ml-1 ${className}`} data-testid="infotip">
      <HelpCircle className="w-3.5 h-3.5 text-ink-muted hover:text-primary cursor-help" aria-hidden />
      <span className="sr-only">{text}</span>
      <span
        role="tooltip"
        className="pointer-events-none absolute left-1/2 top-full z-50 mt-1.5 -translate-x-1/2
                   w-max max-w-[280px] rounded-md bg-[#0f172a] text-white text-[11px] leading-snug
                   px-2.5 py-1.5 opacity-0 group-hover:opacity-100 transition-opacity duration-150
                   shadow-lg whitespace-pre-line"
      >
        {text}
      </span>
    </span>
  );
}
