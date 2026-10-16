# Examples

이 폴더의 코드는 디자인 시스템을 적용한 **참고 구현**입니다. 그대로 복사해서 시작하면 시각적 일관성이 보장됩니다.

## 파일

- `AppShell.tsx` — 표준 페이지 골격 (Sidebar + Topbar + Page header + Content). 모든 어드민 페이지의 출발점.
- `StatusPill.tsx` — 실시간 상태 표시 컴포넌트. running/success/failed/paused/pending.

## 통합 가이드

### 1. Tailwind 프로젝트

```bash
npm install -D tailwindcss
```

`tailwind.config.js`:
```js
const ds = require("./design-system/tokens/tailwind.config.js");

module.exports = {
  content: ["./src/**/*.{ts,tsx,html}"],
  theme: { extend: ds.theme },
  plugins: ds.plugins,
};
```

`src/styles.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@import "../design-system/tokens/tokens.css";
```

### 2. 일반 React / 순수 HTML

`tokens/tokens.css` 만 import 해도 `.btn`, `.card`, `.table`, `.badge` 등 모든 클래스가 작동합니다.

```html
<link rel="stylesheet" href="design-system/tokens/tokens.css" />
```

### 3. shadcn/ui 사용 시

shadcn/ui 의 컴포넌트 변수 (`--primary`, `--border`, `--background` 등) 를 `tokens.css` 의 값으로 매핑하면 자동 적용됩니다. `tokens/shadcn-overrides.css` 참고.

## 권장 폴더 구조

```
src/
├─ components/
│  ├─ app-shell.tsx          ← examples/AppShell.tsx 복사
│  ├─ status-pill.tsx        ← examples/StatusPill.tsx 복사
│  └─ ui/                    ← shadcn/ui 컴포넌트
├─ pages/
│  ├─ dashboard.tsx
│  ├─ sources/
│  │  ├─ index.tsx           ← List
│  │  ├─ [id].tsx            ← Detail
│  │  └─ new.tsx             ← Wizard
│  └─ ...
└─ styles.css
```
