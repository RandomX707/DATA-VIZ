/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Theme-aware (CSS variable-driven)
        bg: 'var(--color-bg)',
        card: 'var(--color-card)',
        'card-hover': 'var(--color-card-hover)',
        surface: 'var(--color-surface)',
        stripe: 'var(--color-stripe)',
        border: 'var(--color-border)',
        text: {
          DEFAULT: 'var(--color-text)',
          muted: 'var(--color-text-muted)',
          dim: 'var(--color-text-dim)',
        },
        // Static (same in both modes)
        accent: {
          DEFAULT: '#6366f1',
          hover: '#4f46e5',
        },
        success: '#22c55e',
        error: '#ef4444',
        warning: '#f59e0b',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'spin-slow': 'spin 1.5s linear infinite',
      },
    },
  },
  plugins: [],
}
