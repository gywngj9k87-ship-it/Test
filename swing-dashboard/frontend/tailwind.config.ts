import type { Config } from 'tailwindcss';

/**
 * Tailwind is wired to the SAME custom properties the mockup declares in
 * app/globals.css. There is no second palette here — every colour resolves to a
 * var(--token) so light/dark and the data-theme override keep working.
 * Do not add raw hex values to this file.
 */
const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}',
  ],
  darkMode: ['class', ':root[data-theme="dark"] &'],
  theme: {
    extend: {
      colors: {
        'surface-1': 'var(--surface-1)',
        plane: 'var(--plane)',
        ink: 'var(--ink)',
        'ink-2': 'var(--ink-2)',
        muted: 'var(--muted)',
        grid: 'var(--grid)',
        axis: 'var(--axis)',
        ring: 'var(--ring)',
        wash: 'var(--wash)',
        s1: 'var(--s1)',
        s2: 'var(--s2)',
        s3: 'var(--s3)',
        good: 'var(--good)',
        warn: 'var(--warn)',
        serious: 'var(--serious)',
        crit: 'var(--crit)',
        up: 'var(--up)',
        down: 'var(--down)',
      },
      borderColor: {
        DEFAULT: 'var(--ring)',
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', '"Segoe UI"', 'sans-serif'],
      },
      fontSize: {
        micro: ['10.5px', '1.4'],
        tiny: ['11.5px', '1.45'],
        small: ['12.5px', '1.5'],
        base: ['14px', '1.5'],
      },
      borderRadius: {
        card: '12px',
        note: '10px',
      },
      maxWidth: {
        wrap: '1280px',
      },
    },
  },
  plugins: [],
};

export default config;
