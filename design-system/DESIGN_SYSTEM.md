# 디자인 시스템 — kspo-ingest

> 운영 콘솔의 시각 어휘. 모든 토큰은 `tokens/tokens.css` 에 CSS 변수로 정의되어 있습니다.

---

## 1. 컬러

### 1.1 베이스 (Surface / Background)

| 토큰 | HEX | 용도 |
|---|---|---|
| `--bg` | `#F8FAFC` | 페이지 배경 |
| `--bg-muted` | `#F1F5F9` | 입력 비활성, 호버, 테이블 헤더 |
| `--surface` | `#FFFFFF` | 카드, 모달, 드롭다운 |
| `--border` | `#E2E8F0` | 기본 보더 |
| `--border-strong` | `#CAD5E2` | 강조 보더 (스크롤 thumb 등) |
| `--border-soft` | `#EDF1F6` | 카드 내부 구분선 |

### 1.2 텍스트

| 토큰 | HEX | 용도 |
|---|---|---|
| `--text` | `#020618` | 본문, 제목 (slate-950) |
| `--text-muted` | `#62748E` | 라벨, 메타 정보 |
| `--text-subtle` | `#6A7282` | placeholder, hint |

### 1.3 Primary

| 토큰 | HEX | 용도 |
|---|---|---|
| `--primary` | `#155DFC` | 주 액션 버튼, 링크, 활성 상태 |
| `--primary-hover` | `#1352E0` | 버튼 호버 |
| `--primary-soft` | `#EFF4FF` | 활성 행 배경, 선택 상태 |
| `--primary-fg` | `#FFFFFF` | primary 위 텍스트 |

### 1.4 시맨틱

| 상태 | Solid | Soft | 사용 |
|---|---|---|---|
| Success | `#16A34A` | `#DCFCE7` | 성공, 정상, 완료 |
| Warning | `#D97706` | `#FFEDD5` | 경고, 주의, 일시정지 |
| Danger  | `#E7000B` | `#FEF2F2` | 실패, 오류, 삭제 |
| Info    | `#0284C7` | `#E0F2FE` | 정보, 진행 중 |
| Purple  | `#9810FA` | —        | 코드/셀렉터 강조 (모노 텍스트) |

**규칙:** 한 화면에 시맨틱 컬러 동시 사용은 최대 3종. 액센트 컬러는 정보 전달 외 장식 용도로 사용 금지.

---

## 2. 타이포그래피

### 2.1 폰트 패밀리

```css
/* Sans - 본문 */
font-family: 'Pretendard', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;

/* Display - 제목, KPI 숫자 */
font-family: 'Geist', 'Inter', sans-serif;

/* Mono - 코드, ID, URL, 시간 */
font-family: 'Geist Mono', 'Menlo', 'Consolas', monospace;
```

폰트 임포트:
```html
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700;800&family=Geist+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>
```

한국어:
```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.min.css"/>
```

### 2.2 스케일

| 용도 | size / line | weight | family |
|---|---|---|---|
| Display (KPI 숫자) | 30 / 36 | 700 | Geist |
| H1 (페이지 제목) | 24 / 32 | 600 | Geist |
| H2 (섹션 제목) | 20 / 28 | 600 | Geist |
| H3 (카드 제목) | 15 / 22 | 600 | Pretendard |
| Body | 14 / 20 | 400 | Pretendard |
| Body strong | 14 / 20 | 500 | Pretendard |
| Small | 13 / 18 | 400 | Pretendard |
| Caption | 12 / 16 | 500 | Pretendard |
| Label (uppercase) | 11 / 14 | 500, letter-spacing .04em | Pretendard |
| Mono | 12.5 / 18 | 400 | Geist Mono |

**규칙:**
- 14px 미만 본문 텍스트 사용 금지
- 숫자는 항상 `font-variant-numeric: tabular-nums`
- 한국어 본문은 `text-wrap: pretty`

---

## 3. 간격 (Spacing)

4px 그리드 기반 8단계 스케일.

| 토큰 | 값 | 용도 |
|---|---|---|
| `space-0` | 0 | — |
| `space-1` | 4px | 인라인 간격, 아이콘 ↔ 텍스트 |
| `space-2` | 8px | 작은 컴포넌트 내부 |
| `space-3` | 12px | 폼 컨트롤 사이 |
| `space-4` | 16px | 카드 사이, 행 사이 |
| `space-5` | 20px | 카드 패딩 (default) |
| `space-6` | 24px | 섹션 사이 |
| `space-8` | 32px | 페이지 헤더 ↔ 콘텐츠 |
| `space-12` | 48px | 큰 영역 분리 |

---

## 4. Border Radius

| 토큰 | 값 | 용도 |
|---|---|---|
| `--radius-sm` | 6px | 작은 버튼, 배지 (pill 제외), input small |
| `--radius` | 8px | 기본 버튼, input, 작은 카드, 배지 박스형 |
| `--radius-lg` | 12px | 카드, 모달, 큰 패널 |
| pill | 999px | status pill, 배지 둥근형 |

**규칙:** 다른 값(예: 4, 10, 16) 임의 사용 금지.

---

## 5. Shadow

| 토큰 | 값 | 용도 |
|---|---|---|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | input focus halo, hover lift |
| `--shadow-md` | `0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)` | dropdown |
| `--shadow-lg` | `0 10px 30px rgba(2,6,24,0.08), 0 4px 10px rgba(2,6,24,0.04)` | modal, toast, popover |

**규칙:** 카드 자체에 shadow 사용 금지 — 보더로만 표현. shadow는 floating element 전용.

---

## 6. Icon

- 라이브러리: **lucide-react** (또는 lucide static SVG)
- 기본 사이즈: 16px (텍스트 옆), 18px (버튼 단독), 14px (배지 안)
- stroke-width: 1.75 (lucide 기본)
- 색상: 텍스트와 동일 (`color: currentColor`), 메타 영역은 `var(--text-muted)`

---

## 7. 그리드 / 너비

- **Sidebar:** 248px (확장) / 68px (접힘)
- **Topbar:** 56px height
- **Page max-width:** 1280px (`.page-max`)
- **Form max-width:** 600px (single column form 기준)
- **Modal width:** 480px (small) / 640px (default) / 880px (large)
- **Table:** 100% width, min-width: 768px (overflow-x: auto)

---

## 8. Motion

| 용도 | duration | easing |
|---|---|---|
| 컬러 / 보더 / 배경 hover | 120ms | ease-out |
| 패널 펼침/접힘 | 200ms | cubic-bezier(.4,0,.2,1) |
| 모달 / 드롭다운 등장 | 160ms | ease-out |
| 페이지 전환 | 240ms | ease-in-out |

**규칙:** transition: all 사용 금지. 변경 속성을 명시.

---

## 9. 컬러 사용 매트릭스

| 상황 | 컬러 |
|---|---|
| 첫 페이지 진입, 정상 운영 중 | success / info / 무채 |
| 사용자 주의 필요 | warning |
| 즉시 조치 필요 | danger (단, 1화면 1개만 도드라지게) |
| 마케팅 / 강조 | primary (절제) |
| 데이터 시리즈 | primary → success → warning → purple → info 순 |

---

## 10. 다크 모드

현재 라이트 테마만 정의. 다크 추가 시:
- `--bg`: `#0F172A` (slate-900)
- `--surface`: `#1E293B` (slate-800)
- `--text`: `#F1F5F9` (slate-100)
- 컬러 soft 변형은 alpha 8% 적용
