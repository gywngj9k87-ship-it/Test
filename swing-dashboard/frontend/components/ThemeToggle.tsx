'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

/**
 * Light / dark toggle. Writes `data-theme` on <html>, which is what
 * app/globals.css keys the explicit override off.
 *
 * With no stored preference we set nothing, so the
 * `@media (prefers-color-scheme: dark)` block in globals.css governs and the
 * OS wins. The moment the user clicks, `data-theme` is written and persisted,
 * and it overrides the media query from then on.
 */

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'swing-dashboard-theme';

interface ThemeCtx {
  theme: Theme | null;
  setTheme: (t: Theme) => void;
  toggle: () => void;
}

const Ctx = createContext<ThemeCtx>({
  theme: null,
  setTheme: () => {},
  toggle: () => {},
});

export function useTheme() {
  return useContext(Ctx);
}

/** Runs before paint so an explicit choice never flashes the wrong theme. */
export const THEME_BOOT_SCRIPT = `(function(){try{var t=localStorage.getItem('${STORAGE_KEY}');if(t==='dark'||t==='light'){document.documentElement.setAttribute('data-theme',t);}}catch(e){}})();`;

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme | null>(null);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === 'dark' || stored === 'light') setThemeState(stored);
    } catch {
      /* storage blocked — fall back to the OS preference, which already works */
    }
  }, []);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    document.documentElement.setAttribute('data-theme', t);
    try {
      window.localStorage.setItem(STORAGE_KEY, t);
    } catch {
      /* non-fatal */
    }
  }, []);

  const toggle = useCallback(() => {
    const current =
      document.documentElement.getAttribute('data-theme') ??
      (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    setTheme(current === 'dark' ? 'light' : 'dark');
  }, [setTheme]);

  const value = useMemo(() => ({ theme, setTheme, toggle }), [theme, setTheme, toggle]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export default function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const [resolved, setResolved] = useState<Theme>('dark');

  useEffect(() => {
    const attr = document.documentElement.getAttribute('data-theme');
    if (attr === 'dark' || attr === 'light') {
      setResolved(attr);
    } else {
      setResolved(window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    }
  }, [theme]);

  return (
    <button
      className="btn"
      onClick={toggle}
      aria-label={`Switch to ${resolved === 'dark' ? 'light' : 'dark'} theme`}
    >
      {resolved === 'dark' ? '◐ Light' : '◑ Dark'}
    </button>
  );
}
