import { useEffect, useState } from 'react'

// Persists an explicit light/dark choice; defaults to the OS setting.
function getInitial() {
  if (typeof localStorage !== 'undefined') {
    const saved = localStorage.getItem('terra-theme')
    if (saved === 'light' || saved === 'dark') return saved
  }
  return null // follow OS
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(getInitial)

  useEffect(() => {
    const root = document.documentElement
    if (theme) {
      root.setAttribute('data-theme', theme)
      localStorage.setItem('terra-theme', theme)
    } else {
      root.removeAttribute('data-theme')
      localStorage.removeItem('terra-theme')
    }
  }, [theme])

  const isDark =
    theme === 'dark' ||
    (theme === null &&
      typeof matchMedia !== 'undefined' &&
      matchMedia('(prefers-color-scheme: dark)').matches)

  return (
    <button
      className="btn btn--ghost"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      aria-label={`Switch to ${isDark ? 'light' : 'dark'} mode`}
      title={`Switch to ${isDark ? 'light' : 'dark'} mode`}
    >
      {isDark ? '☀' : '☾'}
    </button>
  )
}
