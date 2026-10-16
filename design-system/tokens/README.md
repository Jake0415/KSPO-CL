# 디자인 토큰 가이드

> 토큰은 3단 계층 구조입니다. 항상 **semantic / component** 토큰을 사용하고, primitive 는 직접 참조하지 마세요.

```
foundation.css   ← Primitive (--blue-600, --space-4)
     ↓
semantic.css     ← Semantic   (--color-primary, --color-text)
     ↓
tokens.css       ← Component  (--button-height, --card-padding) + 유틸 클래스
```

## 파일

| 파일 | 토큰 종류 | 사용 |
|---|---|---|
| `foundation.css` | Primitive — color scales (50-950), spacing, sizes, radii, shadows, fonts, motion, z-index, opacity, blur, breakpoints, aspect-ratios | 새 시맨틱 토큰 정의할 때만 참조 |
| `semantic.css` | Semantic — 의미 기반 (`--color-text`, `--color-surface`, `--color-primary`) + 다크 모드 + reduced-motion | **컴포넌트 작성 시 사용** |
| `tokens.css` | Component — `.btn`, `.card`, `.table` 클래스 + 컴포넌트별 토큰 | HTML 에서 직접 import |
| `tokens.json` | DTCG 형식 | Style Dictionary 변환용 |
| `tailwind.config.js` | Tailwind 매핑 | Tailwind 프로젝트 |
| `shadcn-overrides.css` | shadcn/ui 변수 매핑 | shadcn/ui 사용 시 |

## 토큰 카테고리 (총 300+ 토큰)

### 1. Color
- **Primitive scale** — 8개 컬러 × 11단계 = 88개 (slate, blue, green, amber, red, sky, violet, pink, teal)
- **Semantic** — bg / surface / border / text / primary / success / warning / danger / info / accent (각 base/hover/pressed/soft/strong/fg 변형)
- **Data viz** — `--color-data-1` ~ `--color-data-10`, `--color-heat-1` ~ `--color-heat-5`
- **Interaction** — focus ring, overlay, scrim, hover/pressed overlays

### 2. Spacing — `--space-0` ~ `--space-64` (4px base, 28단계)

### 3. Sizing
- Control heights: xs/sm/md/lg/xl
- Icon: 12/14/16/18/20/24/32
- Avatar: 20/24/32/40/48/64/96
- Layout: sidebar/topbar/page-max/form-max/modal/drawer

### 4. Radius — none/xs/sm/md/default/lg/xl/2xl/3xl/full

### 5. Shadow — xs/sm/md/lg/xl/2xl/inner + focus rings (3종)

### 6. Typography
- Font families: sans / display / mono
- Weights: thin (100) ~ black (900)
- Sizes: 2xs (10px) ~ 9xl (72px)
- Line heights: none/tight/snug/normal/relaxed/loose
- Letter spacing: tighter/tight/normal/wide/wider/widest

### 7. Motion — duration (8단계) × easing (6종)

### 8. Z-index — base/raised/dropdown/sticky/fixed/overlay/modal/popover/tooltip/toast

### 9. Component tokens
버튼·인풋·카드·배지·테이블·모달·토스트·툴팁·사이드바·토파바 별 전용 토큰.

### 10. 다크 모드
`.dark` 클래스 / `[data-theme="dark"]` / `prefers-color-scheme` 자동 매핑.

## 사용 예시

```css
/* ✅ 권장 — semantic / component 토큰 */
.my-card {
  background: var(--card-bg);
  border: var(--border-1) solid var(--card-border);
  border-radius: var(--card-radius);
  padding: var(--card-padding);
  color: var(--color-text);
}

.my-button {
  height: var(--button-height-sm);
  background: var(--color-primary);
  color: var(--color-primary-fg);
  transition: background var(--motion-hover);
}

/* ❌ 비권장 — primitive 직접 사용 */
.bad {
  background: var(--blue-600);  /* → var(--color-primary) 사용 */
  padding: 16px;                /* → var(--space-4) 사용 */
}
```

## 다크 모드 적용

```html
<html class="dark">             <!-- 강제 다크 -->
<html data-theme="dark">        <!-- 강제 다크 -->
<html data-theme="auto">        <!-- 시스템 따라가기 -->
```

## 새 토큰 추가 규칙

1. **Primitive** 추가 → `foundation.css`. 스케일 단위로 추가 (단발성 컬러 금지).
2. **Semantic** 추가 → `semantic.css`. `--color-{role}-{variant}` 패턴 유지.
3. **Component** 추가 → `tokens.css`. `--{component}-{property}` 패턴 유지.
4. 다크 모드에서 다른 값을 가져야 하면 `.dark` 블록에 매핑 추가.
5. Tailwind 매핑이 필요하면 `tailwind.config.js` 동기 업데이트.
