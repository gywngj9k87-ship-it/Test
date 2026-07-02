import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from 'recharts'
import ChartTooltip from './ChartTooltip.jsx'

/*
 * One chart component, driven by `form`. Colours are CSS custom properties
 * (`var(--series-N)`) so they follow light/dark automatically. Marks follow
 * the data-viz spec: thin 2px lines, ≥8px active dots, recessive gridlines,
 * and a hover crosshair+tooltip on every plotted form.
 */

const AXIS = 'var(--text-muted)'
const GRID = 'var(--gridline)'

function cssVar(name) {
  return `var(--${name})`
}

const commonAxisProps = {
  tick: { fill: AXIS, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: 'var(--baseline)' },
}

export default function TrendChart({
  form,
  data,
  keys, // multi-series metadata (optional)
  unit,
  decimals = 1,
  height = 260,
  logY = false,
  xKey = 'year',
}) {
  const tooltip = (
    <Tooltip
      cursor={{ stroke: 'var(--baseline)', strokeWidth: 1 }}
      content={<ChartTooltip unit={unit} decimals={decimals} />}
    />
  )

  // ---- Single-series forms ----
  if (form === 'line' || form === 'area') {
    const isArea = form === 'area'
    const Chart = isArea ? AreaChart : LineChart
    const gradId = `grad-${Math.abs(hashKeys(data))}`
    return (
      <ResponsiveContainer width="100%" height={height}>
        <Chart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          {isArea && (
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={cssVar('series-1')} stopOpacity={0.28} />
                <stop offset="100%" stopColor={cssVar('series-1')} stopOpacity={0.02} />
              </linearGradient>
            </defs>
          )}
          <CartesianGrid stroke={GRID} strokeDasharray="0" vertical={false} />
          <XAxis dataKey={xKey} {...commonAxisProps} minTickGap={28} />
          <YAxis
            {...commonAxisProps}
            width={44}
            domain={logY ? ['auto', 'auto'] : ['auto', 'auto']}
            scale={logY ? 'log' : 'auto'}
          />
          {tooltip}
          {isArea ? (
            <Area
              type="monotone"
              dataKey="value"
              name={unit || 'Value'}
              stroke={cssVar('series-1')}
              strokeWidth={2}
              fill={`url(#${gradId})`}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface-1)' }}
            />
          ) : (
            <Line
              type="monotone"
              dataKey="value"
              name={unit || 'Value'}
              stroke={cssVar('series-1')}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface-1)' }}
            />
          )}
        </Chart>
      </ResponsiveContainer>
    )
  }

  // ---- Multi-line (e.g. clean-tech costs, catastrophe losses) ----
  if (form === 'multiline') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey={xKey} {...commonAxisProps} minTickGap={28} />
          <YAxis
            {...commonAxisProps}
            width={46}
            scale={logY ? 'log' : 'auto'}
            domain={logY ? ['auto', 'auto'] : ['auto', 'auto']}
            allowDataOverflow={false}
          />
          {tooltip}
          {keys.map((k) => (
            <Line
              key={k.key}
              type="monotone"
              dataKey={k.key}
              name={k.label}
              stroke={cssVar(k.series)}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface-1)' }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    )
  }

  // ---- Stacked area (electricity mix) ----
  if (form === 'stacked') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey={xKey} {...commonAxisProps} minTickGap={28} />
          <YAxis
            {...commonAxisProps}
            width={48}
            domain={[0, 100]}
            ticks={[0, 25, 50, 75, 100]}
            allowDecimals={false}
            tickFormatter={(v) => `${v}%`}
          />
          {tooltip}
          {keys.map((k) => (
            <Area
              key={k.key}
              type="monotone"
              dataKey={k.key}
              name={k.label}
              stackId="1"
              stroke={cssVar(k.series)}
              strokeWidth={1}
              fill={cssVar(k.series)}
              fillOpacity={0.82}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    )
  }

  // ---- Vertical bars (single series over time) ----
  if (form === 'bar') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey={xKey} {...commonAxisProps} minTickGap={16} />
          <YAxis {...commonAxisProps} width={44} />
          {tooltip}
          <Bar dataKey="value" name={unit || 'Value'} fill={cssVar('series-1')} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    )
  }

  // ---- Horizontal bars (categorical, e.g. emissions by sector) ----
  if (form === 'hbar') {
    return (
      <ResponsiveContainer width="100%" height={Math.max(height, data.length * 30)}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 16, left: 8, bottom: 4 }}
        >
          <CartesianGrid stroke={GRID} horizontal={false} />
          <XAxis type="number" {...commonAxisProps} />
          <YAxis
            type="category"
            dataKey="sector"
            {...commonAxisProps}
            width={168}
            tick={{ fill: 'var(--text-secondary)', fontSize: 11.5 }}
          />
          {tooltip}
          <Bar dataKey="value" name={unit || 'Share'} radius={[0, 3, 3, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={cssVar(`series-${(i % 8) + 1}`)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    )
  }

  return null
}

// Deterministic small hash so each area chart gets a unique gradient id.
function hashKeys(data) {
  const s = data && data.length ? `${data[0][Object.keys(data[0])[0]]}-${data.length}` : 'x'
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return h
}
