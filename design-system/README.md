# kspo-ingest Design System

kspo-ingest 운영 콘솔의 시각적 컨셉을 다른 화면/메뉴로 확장하기 위한 디자인 가이드입니다.

## 시작하기

**Claude Code에서 작업할 때:** 먼저 [`CLAUDE.md`](./CLAUDE.md) 를 읽으세요.

## 문서

| 파일 | 내용 |
|---|---|
| [`CLAUDE.md`](./CLAUDE.md) | Claude Code용 작업 지침 — **가장 먼저 읽을 것** |
| [`DESIGN_SYSTEM.md`](./DESIGN_SYSTEM.md) | 컬러·타이포·간격·반경 등 디자인 토큰 정의 |
| [`COMPONENTS.md`](./COMPONENTS.md) | 버튼/카드/테이블/배지 등 컴포넌트 카탈로그 |
| [`PATTERNS.md`](./PATTERNS.md) | 페이지 레이아웃, 상태 표시, 인터랙션 패턴 |

## 토큰

| 파일 | 용도 |
|---|---|
| `tokens/tokens.css` | CSS 변수 + 유틸리티 클래스 (vanilla) |
| `tokens/tokens.json` | DTCG 형식 토큰 (Style Dictionary 등) |
| `tokens/tailwind.config.js` | Tailwind 설정 |
| `tokens/shadcn-overrides.css` | shadcn/ui 변수 오버라이드 |

## 예제

| 파일 | 내용 |
|---|---|
| `examples/AppShell.tsx` | 표준 페이지 골격 (React + Tailwind) |
| `examples/StatusPill.tsx` | 실시간 상태 표시 컴포넌트 |
| `examples/README.md` | 통합 가이드 |

## 핵심 원칙

1. **Primary blue (#155DFC) 외 컬러 사용 시 사전 합의 필수**
2. **카드는 `border-radius: 12px`, 보더는 `#E2E8F0`**
3. **상태 표시는 항상 컬러 + 아이콘 + 텍스트**
4. **숫자는 `tabular-nums`, 코드/ID는 Geist Mono**
5. **그라디언트, 이모지, AI tropes 지양**

## 라이선스

내부 사용 — kspo-ingest 프로젝트.
