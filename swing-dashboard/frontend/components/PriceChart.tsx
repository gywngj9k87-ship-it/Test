'use client';

/**
 * The price panel — the one chart that runs on `lightweight-charts`.
 *
 * Everything else in the dashboard is SVG (LineChart) or Recharts. Price gets
 * the specialist because it needs a real time axis, crosshair scrubbing and
 * pan/zoom over a long daily series.
 *
 * The chart rules still apply. In particular: close, EMA 20 and EMA 50 are all
 * prices, so they share ONE axis — there is no second scale for the overlays.
 * Colours are read out of the CSS custom properties at runtime (canvas can't
 * resolve `var()`), so the palette stays single-sourced in globals.css, and the
 * chart re-themes when `data-theme` changes.
 */

import { useEffect, useRef, useState } from 'react';

export interface PriceSeries {
  label: string;
  /** CSS custom property NAME, e.g. '--s1'. Resolved at runtime. */
  token: string;
  values: Array<number | null>;
  lineWidth?: 1 | 2 | 3 | 4;
}

export interface PriceChartProps {
  /** ISO dates ('2026-08-05'), aligned with every series. */
  dates: string[];
  series: PriceSeries[];
  height?: number;
  ariaLabel: string;
}

function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export default function PriceChart({
  dates,
  series,
  height = 320,
  ariaLabel,
}: PriceChartProps) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [themeTick, setThemeTick] = useState(0);
  const [failed, setFailed] = useState(false);

  // Re-render the canvas whenever the theme flips.
  useEffect(() => {
    const mo = new MutationObserver(() => setThemeTick((t) => t + 1));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onMq = () => setThemeTick((t) => t + 1);
    mq.addEventListener('change', onMq);
    return () => {
      mo.disconnect();
      mq.removeEventListener('change', onMq);
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    let cleanup: (() => void) | undefined;

    (async () => {
      const el = boxRef.current;
      if (!el) return;
      let mod: typeof import('lightweight-charts');
      try {
        mod = await import('lightweight-charts');
      } catch {
        setFailed(true);
        return;
      }
      if (disposed || !boxRef.current) return;
      el.innerHTML = '';

      const ink = cssVar('--ink-2', '#52514e');
      const gridColor = cssVar('--grid', '#e1e0d9');
      const surface = cssVar('--surface-1', '#fcfcfb');
      const axis = cssVar('--axis', '#c3c2b7');

      const chart = mod.createChart(el, {
        height,
        layout: {
          background: { color: surface },
          textColor: ink,
          fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
          fontSize: 11,
          attributionLogo: false,
        },
        grid: {
          vertLines: { color: gridColor },
          horzLines: { color: gridColor },
        },
        rightPriceScale: { borderColor: axis },
        timeScale: { borderColor: axis, fixLeftEdge: true, fixRightEdge: true },
        crosshair: {
          vertLine: { color: axis, width: 1, style: 0, labelBackgroundColor: ink },
          horzLine: { color: axis, width: 1, style: 0, labelBackgroundColor: ink },
        },
        handleScale: { axisPressedMouseMove: false },
      });

      for (const s of series) {
        const line = chart.addLineSeries({
          color: cssVar(s.token, '#2a78d6'),
          lineWidth: s.lineWidth ?? 2,
          title: s.label,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: true,
        });
        line.setData(
          s.values
            .map((v, i) => ({ time: dates[i] as never, value: v as number }))
            .filter((p) => p.value != null && !Number.isNaN(p.value)),
        );
      }

      chart.timeScale().fitContent();

      const ro = new ResizeObserver(() => chart.timeScale().fitContent());
      ro.observe(el);

      cleanup = () => {
        ro.disconnect();
        chart.remove();
      };
    })();

    return () => {
      disposed = true;
      cleanup?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dates, series, height, themeTick]);

  if (failed) {
    return (
      <p className="cap" style={{ margin: 0 }}>
        Price chart could not load. The table view below carries the same numbers.
      </p>
    );
  }

  return (
    <div
      ref={boxRef}
      className="chartbox"
      role="img"
      aria-label={ariaLabel}
      style={{ minHeight: height }}
    />
  );
}
