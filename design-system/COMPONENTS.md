# 컴포넌트 카탈로그

> 모든 컴포넌트는 `tokens/tokens.css` 의 클래스로 즉시 사용 가능. React/Tailwind 사용 시 `examples/` 의 JSX 스니펫 참고.

---

## Button

```html
<button class="btn btn-primary">생성</button>
<button class="btn btn-outline btn-sm">취소</button>
<button class="btn btn-ghost btn-icon"><svg.../></button>
<button class="btn btn-destructive">삭제</button>
```

| variant | 용도 |
|---|---|
| `btn-primary` | 주 액션 (페이지당 1개 권장) |
| `btn-outline` | 보조 액션, 폼 secondary |
| `btn-ghost` | 아이콘 버튼, 링크형 |
| `btn-secondary` | 회색 배경 액션 |
| `btn-destructive` | 삭제, 위험 액션 |

| size | height | font |
|---|---|---|
| (default) | 36 | 14 |
| `btn-sm` | 32 | 13 |
| `btn-xs` | 26 | 12 |

**규칙:** 버튼 안 아이콘은 항상 텍스트의 좌측. gap: 6px.

---

## Input / Form

```html
<label class="label">소스 이름 *</label>
<input class="input" placeholder="예) KSPO 보도자료"/>
<div class="helper">대시보드에 표시되는 식별 가능한 이름</div>

<textarea class="input textarea"/>
<select class="input">…</select>
```

- 모든 input: height 36, radius 8, border 1px
- focus: primary border + 3px halo
- 필수 필드는 라벨에 `*` (붉은색 X — 그냥 별표만)

---

## Card

```html
<div class="card">
  <div class="card-header">
    <div>
      <div class="card-title">섹션 제목</div>
      <div class="card-desc">부가 설명</div>
    </div>
    <div><!-- actions --></div>
  </div>
  <div class="card-body">…</div>
</div>
```

- border 1px, radius 12, surface 배경
- header padding 18 / 20, body padding 20
- shadow 사용 안 함

---

## Badge

```html
<span class="badge badge-success">정상</span>
<span class="badge badge-warning badge-dot">대기</span>
<span class="badge badge-info">진행 중</span>
```

| variant | 용도 |
|---|---|
| `badge-success` | 정상, 완료 |
| `badge-warning` | 일시정지, 주의 |
| `badge-danger` | 실패, 오류 |
| `badge-info` | 진행 중, 정보 |
| `badge-neutral` | 비활성, 카운트 |
| `badge-primary` | 강조 |

`badge-dot` 추가 시 좌측에 6px 점.

---

## Status Pill (실시간 상태)

```jsx
<StatusPill status="running" />
// → 파동 도트 + 텍스트
```

| status | 점 컬러 | 라벨 |
|---|---|---|
| running | success (pulse) | 실행 중 |
| success | success | 성공 |
| failed  | danger  | 실패 |
| paused  | warning | 일시정지 |
| pending | text-muted | 대기 |

---

## Table

```html
<table class="table">
  <thead><tr><th>컬럼</th>…</tr></thead>
  <tbody>
    <tr class="row-clickable" onclick="…">
      <td>값</td>…
    </tr>
  </tbody>
</table>
```

- 헤더 배경 `bg-muted`, 텍스트 12px / muted
- row hover: `bg`
- row 클릭 가능 시 `row-clickable` 추가
- 숫자 컬럼은 `text-align: right; font-variant-numeric: tabular-nums`
- 코드/ID는 `<span class="mono">`

---

## Tabs

```html
<div class="tabs">
  <button class="tab tab-active">사용자</button>
  <button class="tab">역할</button>
  <button class="tab">감사 로그</button>
</div>
```

- 하단 보더 1px, 활성 탭은 primary 2px 보더
- 13px / weight 500
- 카운트 표시 시 우측에 `badge-neutral`

---

## Code Block

```html
<pre class="code-block">
{ "key": "value" }
</pre>
```

- 다크 배경 (#0F172A), Geist Mono, 12.5px
- 토큰 강조: `c-key`, `c-str`, `c-num`, `c-com`

---

## Toast

화면 하단 중앙 고정. 한 번에 하나만.

```html
<div class="toast">
  <svg.../> 새 인제스트가 생성되었습니다
</div>
```

- 배경 `#020618`, 텍스트 흰색, radius 8, padding 10/16
- shadow-lg, 2.4초 후 자동 소멸

---

## Avatar

```html
<div class="avatar" style="background: #155DFC">김운</div>
```

- 32px, radius 999, 텍스트 흰색 12px / 700
- 컬러는 사용자별 hash로 결정 (palette: primary / info / warning / success)

---

## Sidebar (Nav)

```html
<aside class="sidebar">
  <div class="sidebar-brand">…</div>
  <nav class="sidebar-nav">
    <a class="nav-item nav-active">…</a>
    <a class="nav-item">…</a>
  </nav>
  <div class="sidebar-foot">user chip</div>
</aside>
```

- 너비 248 / 68 (collapsed)
- 활성 아이템: `primary-soft` 배경, primary 텍스트, 좌측 2px primary bar
- 호버: `bg-muted`
- 카운트 배지는 우측

---

## Topbar / Breadcrumbs

```html
<header class="topbar">
  <nav class="breadcrumbs">
    <span>홈</span> <chevron-right/> <span>데이터 소스</span>
  </nav>
  <div class="topbar-actions">
    <button class="btn btn-ghost btn-sm btn-icon">🔍</button>
    <button class="btn btn-ghost btn-sm btn-icon">🔔</button>
  </div>
</header>
```

- height 56, 하단 보더 1px
- breadcrumb 구분자 chevron-right 14px / muted

---

## Drawer / Side Panel

상세 정보 표시 (예: 로그 상세).

- 우측 480px 고정, 카드 스타일
- 닫기 버튼은 우상단 ghost icon
- 본문은 메타 정보 그리드 + 코드 블록

---

## Dialog / Modal

```
┌─────────────────────────┐
│ 제목                   ✕│
│ 부가 설명               │
├─────────────────────────┤
│ 본문                   │
├─────────────────────────┤
│            [취소][확인] │
└─────────────────────────┘
```

- 배경 surface, radius 12, shadow-lg
- 너비 480 / 640 / 880
- 백드롭: `rgba(2,6,24,0.5)` + backdrop-blur(2px)

---

## Wizard Steps

```html
<aside class="step-rail">
  <div class="step step-done">…</div>
  <div class="step step-active">…</div>
  <div class="step">…</div>
</aside>
```

- 너비 260
- 활성/완료: primary 28px 동그라미
- 미완료: surface + border-strong
- 단계 사이 2px 세로 선 (완료 시 primary)

---

## Sparkline / Chart

- SVG 인라인, 단색 라인 + 미세한 area 그라디언트
- 그리드: 4단 가로선, `border-soft`
- 축 텍스트 11px / muted
- 데이터 시리즈 컬러: 1차 primary / 2차 success / 3차 warning

---

## Health map (Heat grid)

8×n 그리드, 각 셀 4px gap. 컬러 스케일:

| 상태 | 컬러 |
|---|---|
| 90%+ | `#16A34A` |
| 70–90 | `#86EFAC` |
| 40–70 | `#FCD34D` |
| 20–40 | `#FB923C` |
| 0–20 | `#E7000B` |

빈 셀은 opacity 0.15.

---

## Empty State

```
┌────────────────────────┐
│        [아이콘]        │
│   "아직 인제스트가     │
│    없습니다"           │
│  부가 설명 1줄         │
│   [+ 새 인제스트]      │
└────────────────────────┘
```

- 아이콘 48px / muted
- 제목 16 / 600, 설명 13 / muted
- 행동 버튼 1개만, primary
