# Claude Code 작업 지침 — kspo-ingest 디자인 시스템

이 폴더는 **kspo-ingest** 운영 콘솔의 디자인 컨셉을 다른 화면/메뉴로 확장할 때 사용하는 디자인 시스템 가이드입니다. 기능은 변경되더라도 **시각적 일관성**을 유지하기 위해 사용합니다.

## 작업 시작 전 반드시 읽을 것

1. `DESIGN_SYSTEM.md` — 컬러·타이포·간격·반경 등 디자인 토큰 정의
2. `COMPONENTS.md` — 버튼, 카드, 테이블, 배지 등 재사용 컴포넌트 카탈로그
3. `PATTERNS.md` — 페이지 레이아웃, 상태 표시, 인터랙션 패턴
4. `tokens/tokens.css` — CSS 변수 (직접 import 가능)
5. `tokens/tailwind.config.js` — Tailwind 사용 시 설정

## 핵심 원칙 (절대 위반 금지)

- **Primary blue (#155DFC) 외 컬러 사용 시 사전 합의 없이 변경 금지**
- **모든 표면(card)은 `border-radius: 12px`, 보더는 `#E2E8F0`**
- **상태 표시는 항상 컬러 + 아이콘 + 텍스트의 3중 신호**
- **데이터는 단조형 숫자(`tabular-nums`), 코드/ID는 Geist Mono**
- **그라디언트, 아이콘 직접 그리기, 이모지 사용 지양**
- **Pretendard → Inter 순으로 한국어 폰트 우선**

## 새 화면을 만들 때

```
1. examples/ 안의 가장 비슷한 화면을 복사해서 시작
2. DESIGN_SYSTEM.md 의 spacing/typography 토큰만 사용
3. COMPONENTS.md 에 정의된 클래스(.btn, .card, .table, .badge…)를 우선 활용
4. 새 컴포넌트가 필요하면 COMPONENTS.md 에 추가하고 패턴화
5. PATTERNS.md 의 페이지 골격(AppShell, breadcrumbs, page-header) 따르기
```

## 페이지 골격 (AppShell)

모든 어드민 페이지는 다음 골격을 따릅니다:

```
┌─────────────────────────────────────────────────────┐
│ Sidebar (248px)  │  Topbar (breadcrumbs + actions)  │
│  - 로고          ├──────────────────────────────────┤
│  - 메인 메뉴     │  Page header                     │
│  - 관리 메뉴     │   - h1 title                     │
│  - 사용자 칩     │   - subtitle (optional)          │
│                  ├──────────────────────────────────┤
│                  │  Content (max-width: 1280)       │
│                  │   - cards / tables / forms       │
└──────────────────┴──────────────────────────────────┘
```

## 절대 하지 말 것

- ❌ 화려한 그라디언트 배경 (단색 + 미세한 음영만)
- ❌ 보더 + 좌측 액센트 컬러 박스 (AI tropes)
- ❌ 한 페이지에 3개 초과의 액센트 컬러
- ❌ 14px 미만 본문 텍스트 (가독성)
- ❌ 32px 미만 클릭 타겟
- ❌ 임의의 카드 보더 반경 (8/12 외 사용 금지)
- ❌ box-shadow 강한 사용 (--shadow-md 이상은 dropdown/modal에만)

## 권장 라이브러리

기능 구현 시 시각 일관성을 유지하기 위해 다음을 권장합니다:

- **React + Tailwind CSS** — `tokens/tailwind.config.js` 적용
- **shadcn/ui** — Myna UI의 베이스. 그대로 호환
- **Radix UI** — 헤드리스 프리미티브
- **lucide-react** — 아이콘 (이 프로토타입의 아이콘 세트)
- **Geist + Geist Mono** — 폰트 패밀리
- **Pretendard** — 한국어 본문

## Quick Start

새 페이지 시작 코드 (Tailwind 기준):

```tsx
import { AppShell } from "@/components/app-shell";

export default function MyPage() {
  return (
    <AppShell
      title="페이지 제목"
      breadcrumbs={["홈", "현재 메뉴"]}
      actions={<button className="btn btn-primary btn-sm">주요 액션</button>}
    >
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">섹션 제목</h2>
        </div>
        <div className="card-body">…</div>
      </div>
    </AppShell>
  );
}
```

## 참고 화면 (examples/)

각 화면은 컨셉 reference 입니다. 기능은 다르더라도 같은 시각 어휘를 따르세요.

- `examples/dashboard.html` — KPI 카드 + 차트 + 최근 활동
- `examples/list-view.html` — 필터 + 테이블/카드 토글 + 행 클릭 → 상세
- `examples/detail-view.html` — 헤더 메타 + 탭 + 우측 사이드 패널
- `examples/wizard.html` — 좌측 스텝 레일 + 우측 폼
- `examples/login.html` — 분할 레이아웃 (좌 브랜드 / 우 폼)
