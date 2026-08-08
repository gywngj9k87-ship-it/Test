'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { DEFAULT_CONID } from '@/lib/mock';

/**
 * Tab nav. Real links, not buttons — every view is a route, so it is
 * bookmarkable and the back button works. The deep dive routes on CONID, never
 * on symbol (see LeverageBadge for why).
 */

const TABS: Array<{ href: string; label: string; match: (p: string) => boolean }> = [
  { href: '/', label: 'Market overview', match: (p) => p === '/' },
  {
    href: `/deep-dive/${DEFAULT_CONID}`,
    label: 'Deep dive',
    match: (p) => p.startsWith('/deep-dive'),
  },
  { href: '/screens', label: 'Screens', match: (p) => p.startsWith('/screens') },
  { href: '/portfolio', label: 'Portfolio', match: (p) => p.startsWith('/portfolio') },
  { href: '/leverage', label: 'Leverage', match: (p) => p.startsWith('/leverage') },
  { href: '/income', label: 'Income sleeve', match: (p) => p.startsWith('/income') },
];

export default function TabNav() {
  const pathname = usePathname() ?? '/';
  return (
    <nav className="tabs" role="tablist" aria-label="Views">
      {TABS.map((t) => (
        <Link
          key={t.href}
          href={t.href}
          role="tab"
          aria-selected={t.match(pathname)}
          aria-current={t.match(pathname) ? 'page' : undefined}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
