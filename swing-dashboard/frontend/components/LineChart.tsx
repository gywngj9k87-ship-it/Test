'use client';

/* ══════════════════════════════════════════════════════════════════════════
 * NON-NEGOTIABLE CHART RULES
 *
 * Carried over from the approved mockup (dashboard-mockup.html). These are not
 * preferences. They were signed off, and any chart added to this dashboard —
 * SVG, Recharts, lightweight-charts, anything — obeys them.
 *
 *  1. NEVER a dual-axis chart. Two measures of different scale get indexed to
 *     a common base (100) and plotted on ONE axis, or plotted on a log scale.
 *     A second y-axis lets the author choose the story; the reader can't tell.
 *
 *  2. A LEGEND IS ALWAYS PRESENT for two or more series. Direct-label
 *     selectively — the end of each line, deduped for collisions — never a
 *     number on every point.
 *
 *  3. STATUS COLOURS ARE RESERVED. good / warning / serious / critical mean
 *     status and only status, and they always ship with an icon PLUS a text
 *     label so the meaning survives greyscale and colourblindness. Series use
 *     --s1 / --s2 / --s3. Direction uses --up / --down.
 *
 *  4. EVERY CHART HAS A TABLE-VIEW TWIN. If the number matters, it must be
 *     readable as a number. Wrap the chart in <TableView> and give it the same
 *     data.
 *
 *  5. TEXT USES INK TOKENS (--ink / --ink-2 / --muted), NEVER a series colour.
 *     The one exception is a direct end-label, which is the line's own name and
 *     is therefore part of the mark, not prose.
 *
 * Palette values live in app/globals.css and were validated for colourblind
 * separation and contrast. Do not introduce a new one.
 * ══════════════════════════════════════════════════════════════════════════ */

import { useCallback, useEffect, useRef, useState } from 'react';
import { fmt } from '@/lib/format';

export interface ChartSeries {
  /** Values, aligned with `dates`. `null` renders as a break in the line. */
  d: (number | null)[];
  /** A series colour — var(--s1) | var(--s2) | var(--s3). Never a status colour. */
  c: string;
  /** Short label, used by the legend, the tooltip and the direct end-label. */
  lab: string;
}

export interface LineChartProps {
  /** Axis labels, one per point. Sparse entries ('') are allowed. */
  dates: string[];
  series: ChartSeries[];
  /** Full labels for the tooltip when `dates` is sparse. */
  fullDates?: string[];
  height?: number;
  /** Right gutter — widen it when end-labels are long. */
  padRight?: number;
  padLeft?: number;
  min?: number;
  max?: number;
  /** Rule 1's escape hatch: a log scale keeps a 17× range and a flat line legible together. */
  log?: boolean;
  ticks?: number;
  /** Horizontal reference lines, e.g. RSI 30 / 70. */
  bands?: number[];
  /** Direct end-labels. Off for single-series panels where the card title says it. */
  label?: boolean;
  /** Tooltip value formatter. */
  formatValue?: (v: number) => string;
  /** Y-axis tick formatter. */
  formatAxis?: (v: number) => string;
  /** Required — the chart is role="img" and needs a text alternative. */
  ariaLabel: string;
}

interface TipState {
  i: number;
  x: number;
  y: number;
}

/** Width assumed on the server, before the container has been measured. */
const SSR_WIDTH = 1000;

export default function LineChart({
  dates,
  series,
  fullDates,
  height = 300,
  padRight = 58,
  padLeft = 44,
  min,
  max,
  log = false,
  ticks = 5,
  bands,
  label = true,
  formatValue,
  formatAxis,
  ariaLabel,
}: LineChartProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [tip, setTip] = useState<TipState | null>(null);

  /**
   * The viewBox tracks the container's real pixel width, so one SVG unit is
   * always one CSS pixel. Without this, a chart in a half-width card scales the
   * whole viewBox down and the axis labels shrink with it — 10.5px type
   * rendering at 5.5px. Font sizes are a design decision, not a function of
   * how wide the card happens to be.
   */
  const [W, setW] = useState(SSR_WIDTH);
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const measure = () => setW(Math.max(320, Math.round(el.clientWidth)));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const H = height;
  const P = { t: 14, r: padRight, b: 26, l: padLeft };
  const iw = W - P.l - P.r;
  const ih = H - P.t - P.b;

  const all = series.flatMap((s) => s.d).filter((v): v is number => v != null);
  const explicit = min != null || max != null;
  let lo = min ?? (all.length ? Math.min(...all) : 0);
  let hi = max ?? (all.length ? Math.max(...all) : 1);
  if (!explicit) {
    if (log) {
      lo /= 1.1;
      hi *= 1.1;
    } else {
      const pad = (hi - lo) * 0.08 || 1;
      lo -= pad;
      hi += pad;
    }
  }
  if (hi === lo) hi = lo + 1;

  const tf = (v: number) => (log ? Math.log10(Math.max(v, 0.01)) : v);
  const X = (i: number) => P.l + (i * iw) / Math.max(dates.length - 1, 1);
  const Y = (v: number) => P.t + ih - ((tf(v) - tf(lo)) / (tf(hi) - tf(lo))) * ih;

  const tickVals: number[] = [];
  for (let i = 0; i <= ticks; i++) {
    tickVals.push(
      log
        ? Math.pow(10, tf(lo) + (tf(hi) - tf(lo)) * (i / ticks))
        : lo + (hi - lo) * (i / ticks),
    );
  }

  const step = Math.ceil(dates.length / 7) || 1;
  const xLabels: Array<{ i: number; text: string }> = [];
  for (let i = 0; i < dates.length; i += step) {
    xLabels.push({ i, text: dates[i] });
  }

  // Direct end-labels, pushed apart when they collide, then nudged back inside.
  const ends = series
    .map((s) => {
      const lastVal = [...s.d].reverse().find((v) => v != null);
      return { y: lastVal == null ? NaN : Y(lastVal), c: s.c, lab: s.lab };
    })
    .filter((e) => !Number.isNaN(e.y))
    .sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) {
    if (ends[i].y - ends[i - 1].y < 16) ends[i].y = ends[i - 1].y + 16;
  }
  const over = ends.length ? ends[ends.length - 1].y - (P.t + ih) : 0;
  if (over > 0) ends.forEach((e) => (e.y -= over));

  const onMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      const svg = svgRef.current;
      if (!svg) return;
      const r = svg.getBoundingClientRect();
      const rx = ((e.clientX - r.left) / r.width) * W;
      let i = Math.round(((rx - P.l) / iw) * (dates.length - 1));
      i = Math.max(0, Math.min(dates.length - 1, i));
      setTip({ i, x: e.clientX, y: e.clientY });
    },
    [dates.length, iw, P.l, W],
  );

  const fv = formatValue ?? ((v: number) => fmt(v));
  const fa = formatAxis ?? ((v: number) => String(Math.round(v)));

  return (
    <div className="chartbox" ref={boxRef}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        style={{ height: H }}
        role="img"
        aria-label={ariaLabel}
        onMouseMove={onMove}
        onMouseLeave={() => setTip(null)}
      >
        <title>{ariaLabel}</title>

        {tickVals.map((v, i) => (
          <g key={`t${i}`}>
            <line className="gl" x1={P.l} x2={P.l + iw} y1={Y(v)} y2={Y(v)} />
            <text className="tick" x={P.l - 8} y={Y(v) + 3.5} textAnchor="end">
              {fa(v)}
            </text>
          </g>
        ))}

        {bands?.map((b) => (
          <line
            key={`b${b}`}
            x1={P.l}
            x2={P.l + iw}
            y1={Y(b)}
            y2={Y(b)}
            stroke="var(--axis)"
            strokeWidth={1}
          />
        ))}

        {xLabels.map(({ i, text }) => (
          <text key={`x${i}`} className="tick" x={X(i)} y={H - 6} textAnchor="middle">
            {text}
          </text>
        ))}

        <line className="ax" x1={P.l} x2={P.l + iw} y1={P.t + ih} y2={P.t + ih} />

        {series.map((s, si) => (
          <polyline
            key={`s${si}`}
            points={s.d
              .map((v, i) => (v == null ? null : `${X(i)},${Y(v)}`))
              .filter(Boolean)
              .join(' ')}
            fill="none"
            stroke={s.c}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}

        {label &&
          ends.map((e, i) => (
            <text key={`e${i}`} className="dl" x={P.l + iw + 7} y={e.y + 4} fill={e.c}>
              {e.lab}
            </text>
          ))}

        {tip && (
          <line
            x1={X(tip.i)}
            x2={X(tip.i)}
            y1={P.t}
            y2={P.t + ih}
            stroke="var(--axis)"
            strokeWidth={1}
          />
        )}

        <rect x={P.l} y={P.t} width={iw} height={ih} fill="transparent" />
      </svg>

      {tip && (
        <div
          className="tipbox"
          style={{
            opacity: 1,
            left: Math.min(tip.x + 14, (typeof window !== 'undefined' ? window.innerWidth : 1200) - 190),
            top: Math.max(8, tip.y - 90),
          }}
          role="status"
        >
          <div className="th">{fullDates?.[tip.i] || dates[tip.i] || ''}</div>
          {series.map((s, i) => {
            const v = s.d[tip.i];
            return (
              <div className="tr" key={`tt${i}`}>
                <span style={{ color: s.c }}>{s.lab}</span>
                <b>{v == null ? '—' : fv(v)}</b>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
