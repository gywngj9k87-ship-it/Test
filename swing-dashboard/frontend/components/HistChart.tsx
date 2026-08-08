'use client';

/**
 * Diverging histogram — the MACD panel from the mockup, rebuilt on Recharts.
 *
 * Follows the rules in components/LineChart.tsx:
 *   * One hue each side of a neutral zero line (--s1 above, --s2 below). These
 *     are SERIES colours, not status colours — a negative MACD bar is not an
 *     error condition.
 *   * The legend is always present and names both sides.
 *   * Ticks and labels use ink tokens.
 *   * Pair it with <TableView> for the table twin.
 */

import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import Legend from './Legend';
import { fmt } from '@/lib/format';

export interface HistChartProps {
  /** Axis labels, one per bar. */
  dates: string[];
  values: number[];
  height?: number;
  /** Legend text for the positive / negative side. */
  aboveLabel?: string;
  belowLabel?: string;
  ariaLabel: string;
}

interface TipPayload {
  active?: boolean;
  payload?: Array<{ payload: { label: string; v: number } }>;
}

function HistTooltip({ active, payload }: TipPayload) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="tipbox" style={{ opacity: 1, position: 'static' }}>
      <div className="th">{p.label}</div>
      <div className="tr">
        <span style={{ color: p.v >= 0 ? 'var(--s1)' : 'var(--s2)' }}>Histogram</span>
        <b>{fmt(p.v, 3)}</b>
      </div>
    </div>
  );
}

export default function HistChart({
  dates,
  values,
  height = 210,
  aboveLabel = 'Above signal',
  belowLabel = 'Below signal',
  ariaLabel,
}: HistChartProps) {
  const data = values.map((v, i) => ({ label: dates[i] ?? '', v }));
  const m = Math.max(...values.map((v) => Math.abs(v)), 0.001) * 1.1;
  const step = Math.ceil(data.length / 7) || 1;

  return (
    <div className="chartbox" role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 12, right: 14, bottom: 4, left: 0 }} barCategoryGap={1}>
          <YAxis
            domain={[-m, m]}
            tickCount={5}
            width={44}
            axisLine={false}
            tickLine={false}
            tick={{ fill: 'var(--muted)', fontSize: 10.5 }}
            tickFormatter={(v: number) => fmt(v, 1)}
          />
          <XAxis
            dataKey="label"
            axisLine={{ stroke: 'var(--axis)' }}
            tickLine={false}
            interval={step - 1}
            tick={{ fill: 'var(--muted)', fontSize: 10.5 }}
          />
          <ReferenceLine y={0} stroke="var(--axis)" />
          <Tooltip cursor={{ fill: 'var(--wash)' }} content={<HistTooltip />} />
          <Bar dataKey="v" radius={[1, 1, 1, 1]} isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.v >= 0 ? 'var(--s1)' : 'var(--s2)'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <Legend
        style={{ margin: '8px 0 0' }}
        items={[
          { color: 'var(--s1)', label: aboveLabel },
          { color: 'var(--s2)', label: belowLabel },
        ]}
      />
    </div>
  );
}
