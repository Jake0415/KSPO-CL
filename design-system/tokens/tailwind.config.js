/** Tailwind 설정 — kspo-ingest 디자인 시스템 (v2 — 확장)
 *
 *  사용:
 *    // tailwind.config.js
 *    const ds = require('./design-system/tokens/tailwind.config.js');
 *    module.exports = {
 *      content: [...],
 *      theme: { extend: ds.theme },
 *      plugins: [...ds.plugins],
 *      darkMode: 'class',
 *    };
 */

module.exports = {
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        // Primitive scales
        slate: {
          50: '#F8FAFC', 100: '#F1F5F9', 200: '#E2E8F0', 300: '#CAD5E2',
          400: '#94A3B8', 500: '#62748E', 600: '#475569', 700: '#314158',
          800: '#1E293B', 900: '#0F172A', 950: '#020618',
        },
        blue: {
          50: '#EFF4FF', 100: '#DBE7FE', 200: '#BEDBFF', 300: '#8EC5FF',
          400: '#51A2FF', 500: '#2B7FFF', 600: '#155DFC', 700: '#1352E0',
          800: '#193CB8', 900: '#1C398E', 950: '#162456',
        },
        green: {
          50: '#F0FDF4', 100: '#DCFCE7', 200: '#B9F8CF', 300: '#7BF1A8',
          400: '#05DF72', 500: '#00C950', 600: '#16A34A', 700: '#008236',
          800: '#016630', 900: '#0D542B', 950: '#032E15',
        },
        amber: {
          50: '#FFFBEB', 100: '#FEF3C6', 200: '#FEE685', 300: '#FFD230',
          400: '#FFB200', 500: '#F59E0B', 600: '#D97706', 700: '#BB4D00',
          800: '#973C00', 900: '#7B3306', 950: '#461901',
        },
        red: {
          50: '#FEF2F2', 100: '#FFE2E2', 200: '#FFC9C9', 300: '#FFA1A1',
          400: '#FF6467', 500: '#FB2C36', 600: '#E7000B', 700: '#C10007',
          800: '#9F0712', 900: '#82181A', 950: '#460809',
        },
        sky: {
          50: '#F0F9FF', 100: '#DFF2FE', 200: '#B8E6FE', 300: '#74D4FF',
          400: '#00BCFF', 500: '#00A6F4', 600: '#0284C7', 700: '#0069A8',
          800: '#00598C', 900: '#024A70', 950: '#052F4A',
        },
        violet: {
          50: '#F5F3FF', 100: '#EDE9FE', 200: '#DDD6FF', 300: '#C3B5FD',
          400: '#A684FF', 500: '#8E51FF', 600: '#7F22FE', 700: '#7008E7',
          800: '#5D0EC0', 900: '#4D179A', 950: '#2F0D68',
        },
        pink: {
          50: '#FDF2F8', 100: '#FCE7F3', 200: '#FBCFE8', 300: '#FDA5D5',
          400: '#FB64B6', 500: '#F6339A', 600: '#E60076', 700: '#C6005C',
          800: '#A3004C', 900: '#861043', 950: '#510424',
        },
        teal: {
          50: '#F0FDFA', 100: '#CBFBF1', 200: '#96F7E4', 300: '#46ECD5',
          400: '#00D5BE', 500: '#00BBA7', 600: '#009689', 700: '#00786F',
          800: '#005F5A', 900: '#0B4F4A', 950: '#022F2E',
        },

        // Semantic — CSS 변수 참조 (다크 모드 자동)
        bg:           { DEFAULT: 'var(--color-bg)', muted: 'var(--color-bg-muted)', subtle: 'var(--color-bg-subtle)', inverse: 'var(--color-bg-inverse)' },
        surface:      { DEFAULT: 'var(--color-surface)', raised: 'var(--color-surface-raised)', overlay: 'var(--color-surface-overlay)', sunken: 'var(--color-surface-sunken)', hover: 'var(--color-surface-hover)', pressed: 'var(--color-surface-pressed)', selected: 'var(--color-surface-selected)' },
        ink:          { DEFAULT: 'var(--color-text)', muted: 'var(--color-text-muted)', subtle: 'var(--color-text-subtle)', inverse: 'var(--color-text-inverse)', link: 'var(--color-text-link)' },
        primary:      { DEFAULT: 'var(--color-primary)', hover: 'var(--color-primary-hover)', pressed: 'var(--color-primary-pressed)', soft: 'var(--color-primary-soft)', strong: 'var(--color-primary-strong)', fg: 'var(--color-primary-fg)' },
        success:      { DEFAULT: 'var(--color-success)', hover: 'var(--color-success-hover)', soft: 'var(--color-success-soft)', strong: 'var(--color-success-strong)', fg: 'var(--color-success-fg)' },
        warning:      { DEFAULT: 'var(--color-warning)', hover: 'var(--color-warning-hover)', soft: 'var(--color-warning-soft)', strong: 'var(--color-warning-strong)', fg: 'var(--color-warning-fg)' },
        danger:       { DEFAULT: 'var(--color-danger)', hover: 'var(--color-danger-hover)', soft: 'var(--color-danger-soft)', strong: 'var(--color-danger-strong)', fg: 'var(--color-danger-fg)' },
        info:         { DEFAULT: 'var(--color-info)', hover: 'var(--color-info-hover)', soft: 'var(--color-info-soft)', strong: 'var(--color-info-strong)', fg: 'var(--color-info-fg)' },
        accent:       { DEFAULT: 'var(--color-accent)', soft: 'var(--color-accent-soft)', fg: 'var(--color-accent-fg)' },
        border:       { DEFAULT: 'var(--color-border)', strong: 'var(--color-border-strong)', soft: 'var(--color-border-soft)', focus: 'var(--color-border-focus)', error: 'var(--color-border-error)' },
      },
      fontFamily: {
        sans:    ['Pretendard', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['Geist', 'Inter', 'ui-sans-serif', 'sans-serif'],
        mono:    ['"Geist Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['10px', '13px'],
        'xs':  ['11px', { lineHeight: '14px', letterSpacing: '0.04em' }],
        'sm':  ['12px', '16px'],
        'base':['13px', '18px'],
        'md':  ['14px', '20px'],
        'lg':  ['15px', '22px'],
        'xl':  ['16px', '24px'],
        '2xl': ['18px', '26px'],
        '3xl': ['20px', '28px'],
        '4xl': ['24px', '32px'],
        '5xl': ['30px', '36px'],
        '6xl': ['36px', '44px'],
        '7xl': ['48px', '56px'],
      },
      fontWeight: {
        thin: '100', extralight: '200', light: '300', regular: '400',
        medium: '500', semibold: '600', bold: '700', extrabold: '800', black: '900',
      },
      letterSpacing: {
        tighter: '-0.04em', tight: '-0.02em', normal: '0',
        wide: '0.02em', wider: '0.04em', widest: '0.08em',
      },
      spacing: {
        '0.5': '2px', '1.5': '6px', '2.5': '10px', '3.5': '14px',
        '4.5': '18px', '13': '52px', '15': '60px', '17': '68px',
      },
      maxWidth: {
        page: '1280px', form: '600px', prose: '720px',
        'modal-sm': '480px', modal: '640px', 'modal-lg': '880px', 'modal-xl': '1120px',
        'drawer-sm': '360px', drawer: '480px', 'drawer-lg': '640px',
      },
      width: {
        sidebar: '248px', 'sidebar-collapsed': '68px',
      },
      height: {
        topbar: '56px',
        'control-xs': '24px', 'control-sm': '28px', 'control-md': '32px',
        'control-lg': '36px', 'control-xl': '40px',
      },
      borderRadius: {
        'none': '0', 'xs': '3px', 'sm': '4px', 'md': '6px',
        DEFAULT: '8px', 'lg': '12px', 'xl': '16px', '2xl': '20px', '3xl': '24px',
        'full': '9999px',
      },
      boxShadow: {
        xs:  '0 1px 2px 0 rgba(2,6,24,0.04)',
        sm:  '0 1px 2px 0 rgba(2,6,24,0.05), 0 1px 1px -1px rgba(2,6,24,0.03)',
        md:  '0 4px 6px -1px rgba(2,6,24,0.06), 0 2px 4px -2px rgba(2,6,24,0.04)',
        lg:  '0 10px 15px -3px rgba(2,6,24,0.08), 0 4px 6px -4px rgba(2,6,24,0.04)',
        xl:  '0 20px 25px -5px rgba(2,6,24,0.10), 0 8px 10px -6px rgba(2,6,24,0.04)',
        '2xl': '0 25px 50px -12px rgba(2,6,24,0.18)',
        focus: '0 0 0 3px rgba(21,93,252,0.20)',
        'focus-danger': '0 0 0 3px rgba(231,0,11,0.20)',
        'focus-success': '0 0 0 3px rgba(22,163,74,0.20)',
      },
      transitionDuration: {
        instant: '0ms', fast: '100ms', quick: '120ms',
        DEFAULT: '160ms', moderate: '200ms', slow: '240ms', slower: '320ms', slowest: '480ms',
      },
      transitionTimingFunction: {
        DEFAULT: 'cubic-bezier(.4,0,.2,1)',
        spring:  'cubic-bezier(.34,1.56,.64,1)',
        emphasis: 'cubic-bezier(.2,0,0,1)',
      },
      zIndex: {
        base: '0', raised: '10', dropdown: '100', sticky: '200',
        fixed: '300', overlay: '400', modal: '500', popover: '600',
        tooltip: '700', toast: '800', debug: '9999',
      },
      backdropBlur: { xs: '2px', md: '12px' },
      keyframes: {
        'pulse-dot':  { '0%,100%': { opacity: '1' }, '50%': { opacity: '.35' } },
        'fade-in':    { from: { opacity: '0' }, to: { opacity: '1' } },
        'slide-up':   { from: { transform: 'translateY(8px)', opacity: '0' }, to: { transform: 'translateY(0)', opacity: '1' } },
        'slide-down': { from: { transform: 'translateY(-8px)', opacity: '0' }, to: { transform: 'translateY(0)', opacity: '1' } },
      },
      animation: {
        'pulse-dot':  'pulse-dot 1.6s infinite',
        'fade-in':    'fade-in 160ms cubic-bezier(0,0,.2,1)',
        'slide-up':   'slide-up 160ms cubic-bezier(0,0,.2,1)',
        'slide-down': 'slide-down 160ms cubic-bezier(0,0,.2,1)',
      },
    },
  },
  plugins: [],
};
