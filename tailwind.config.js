/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        base: 'rgb(var(--c-base) / <alpha-value>)',
        deep: 'rgb(var(--c-deep) / <alpha-value>)',
        surface: 'rgb(var(--c-surface) / <alpha-value>)',
        surface2: 'rgb(var(--c-surface2) / <alpha-value>)',
        panel: 'rgb(var(--c-panel) / <alpha-value>)',
        edge: 'rgb(var(--c-edge) / <alpha-value>)',
        edge2: 'rgb(var(--c-edge2) / <alpha-value>)',
        // Command-center palette. `gold` keeps its token name (used app-wide)
        // but now carries the primary cyan accent.
        gold: '#16B8D4',
        'gold-soft': '#67D3E6',
        steel: '#3B82F6',
        cyan: '#16B8D4',
        sea: '#16B8D4',
        danger: '#EF4444',
        warn: '#F59E0B',
        info: '#3B82F6',
        okay: '#22C55E',
        idle: '#64748B',
      },
      fontFamily: {
        sans: ['Inter', '"Segoe UI"', 'system-ui', 'sans-serif'],
        display: ['Inter', '"Segoe UI"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      // bare `border` utilities use the theme edge colour instead of Tailwind's light gray
      borderColor: {
        DEFAULT: 'var(--border-edge)',
      },
      boxShadow: {
        'neo-raised': 'var(--neo-raised)',
        'neo-raised-sm': 'var(--neo-raised-sm)',
        'neo-inset': 'var(--neo-inset)',
        'neo-inset-sm': 'var(--neo-inset-sm)',
        'glow-gold': '0 0 0 1px rgba(22,184,212,0.35), 0 2px 8px rgba(22,184,212,0.15)',
        'glow-cyan': '0 0 0 1px rgba(22,184,212,0.35), 0 2px 8px rgba(22,184,212,0.15)',
        'glow-red': '0 0 0 1px rgba(239,68,68,0.45), 0 4px 14px rgba(239,68,68,0.25)',
        'glow-amber': '0 0 0 1px rgba(245,158,11,0.4), 0 2px 8px rgba(245,158,11,0.15)',
        panel: '0 8px 24px rgba(0,0,0,0.4)',
      },
      keyframes: {
        'pulse-ring': {
          '0%': { transform: 'scale(1)', opacity: '0.9' },
          '100%': { transform: 'scale(2.8)', opacity: '0' },
        },
        'confirm-pop': {
          '0%': { transform: 'scale(0.85)', opacity: '0' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
        'fade-up': {
          '0%': { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
      },
      animation: {
        'pulse-ring': 'pulse-ring 1.8s cubic-bezier(0.215,0.61,0.355,1) infinite',
        'confirm-pop': 'confirm-pop 0.22s cubic-bezier(0.34,1.56,0.64,1)',
        'fade-up': 'fade-up 0.35s ease-out',
      },
    },
  },
  plugins: [],
}
