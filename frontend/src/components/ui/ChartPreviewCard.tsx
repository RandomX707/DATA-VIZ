import { useState, useEffect, useCallback } from 'react'
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { Trash2, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react'
import { getChartPreview } from '../../api/client'
import type { ChartSpec, DatasetInfo, ChartPreviewData } from '../../types'

const PIE_COLORS = ['#1D9E75', '#534AB7', '#D85A30', '#BA7517', '#185FA5', '#D4537E']

const VIZ_OPTIONS = [
  { value: 'bar', label: 'Bar chart' },
  { value: 'echarts_timeseries_line', label: 'Line chart' },
  { value: 'pie', label: 'Pie chart' },
  { value: 'big_number_total', label: 'Big number' },
  { value: 'table', label: 'Table' },
]

const AGG_OPTIONS = ['SUM', 'COUNT', 'AVG', 'MIN', 'MAX', 'COUNT_DISTINCT']

interface Props {
  chart: ChartSpec
  sessionId: string
  datasetInfo: DatasetInfo
  onRemove: () => void
  onUpdate: (updates: Partial<ChartSpec>) => void
}

function extractMetricInfo(chart: ChartSpec): { metricCol: string; aggregate: string } {
  const m = chart.metrics?.[0]
  if (!m) return { metricCol: '', aggregate: 'SUM' }
  if (typeof m === 'object' && m !== null) {
    const mo = m as Record<string, unknown>
    const col = (mo.column as Record<string, unknown>)?.column_name
    return {
      metricCol: typeof col === 'string' ? col : '',
      aggregate: typeof mo.aggregate === 'string' ? mo.aggregate : 'SUM',
    }
  }
  return { metricCol: '', aggregate: 'SUM' }
}

function buildMetrics(metricCol: string, aggregate: string): Record<string, unknown>[] {
  return [
    {
      expressionType: 'SIMPLE',
      column: { column_name: metricCol },
      aggregate,
      label: `${aggregate}(${metricCol})`,
    },
  ]
}

function formatNumber(n: number): string {
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n.toLocaleString()
}

export default function ChartPreviewCard({ chart, sessionId, datasetInfo, onRemove, onUpdate }: Props) {
  const [preview, setPreview] = useState<ChartPreviewData | null>(null)
  const [loading, setLoading] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [previewKey, setPreviewKey] = useState(0)

  const { metricCol: initMetric, aggregate: initAgg } = extractMetricInfo(chart)
  const [vizType, setVizType] = useState(chart.viz_type)
  const [metricCol, setMetricCol] = useState(initMetric)
  const [aggregate, setAggregate] = useState(initAgg)
  const [dimensionCol, setDimensionCol] = useState(chart.groupby?.[0] ?? '')
  const [timeCol, setTimeCol] = useState(chart.time_column ?? '')
  const [timeGrain, setTimeGrain] = useState(chart.time_grain ?? 'P1M')
  const [title, setTitle] = useState(chart.title)

  const numericCols = datasetInfo.columns.filter((c) => c.type === 'NUMERIC').map((c) => c.column_name)
  const dimCols = datasetInfo.columns.filter((c) => c.type === 'STRING').map((c) => c.column_name)
  const timeCols = datasetInfo.columns.filter((c) => c.type === 'DATETIME' || c.is_dttm).map((c) => c.column_name)

  const fetchPreview = useCallback(async () => {
    if (!metricCol) return
    setLoading(true)
    try {
      const data = await getChartPreview(sessionId, {
        viz_type: vizType,
        metric_col: metricCol,
        aggregate,
        dimension_col: dimensionCol || undefined,
        time_col: timeCol || undefined,
        time_grain: timeGrain,
        row_limit: 10,
      })
      setPreview(data)
    } catch {
      setPreview({ rows: [], error: 'Failed to load preview' })
    } finally {
      setLoading(false)
    }
  }, [sessionId, vizType, metricCol, aggregate, dimensionCol, timeCol, timeGrain])

  useEffect(() => {
    void fetchPreview()
  }, [previewKey, fetchPreview])

  function handleApply() {
    const updates: Partial<ChartSpec> = {
      title,
      viz_type: vizType,
      metrics: buildMetrics(metricCol, aggregate),
      groupby: dimensionCol ? [dimensionCol] : [],
      time_column: timeCol || null,
      time_grain: timeGrain || null,
    }
    onUpdate(updates)
    setPreviewKey((k) => k + 1)
    setEditOpen(false)
  }

  function renderChart() {
    if (loading) {
      return (
        <div className="flex items-center justify-center h-[200px] text-text-muted text-sm">
          Loading preview…
        </div>
      )
    }
    if (!preview) return null
    if (preview.error) {
      return (
        <div className="flex items-center justify-center h-[200px] text-error text-sm px-3 text-center">
          {preview.error}
        </div>
      )
    }

    if (vizType === 'big_number_total') {
      return (
        <div className="flex items-center justify-center h-[200px]">
          <span className="text-4xl font-bold text-accent">
            {preview.total != null ? formatNumber(preview.total) : '—'}
          </span>
        </div>
      )
    }

    if (!preview.rows || preview.rows.length === 0) {
      return (
        <div className="flex items-center justify-center h-[200px] text-text-muted text-sm">
          No data
        </div>
      )
    }

    if (vizType === 'pie') {
      return (
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie data={preview.rows} dataKey="value" nameKey="label" cx="50%" cy="50%" outerRadius={75} label={false}>
              {preview.rows.map((_, i) => (
                <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(v) => (typeof v === 'number' ? formatNumber(v) : v)} />
          </PieChart>
        </ResponsiveContainer>
      )
    }

    if (vizType === 'echarts_timeseries_line') {
      return (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={preview.rows} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
            <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10 }} tickFormatter={formatNumber} width={45} />
            <Tooltip formatter={(v) => (typeof v === 'number' ? formatNumber(v) : v)} />
            <Line type="monotone" dataKey="value" stroke="#6366f1" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      )
    }

    if (vizType === 'table') {
      return (
        <div className="overflow-auto max-h-[200px]">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="bg-surface">
                <th className="text-left px-2 py-1 border-b border-border text-text-muted">Label</th>
                <th className="text-right px-2 py-1 border-b border-border text-text-muted">Value</th>
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((r, i) => (
                <tr key={i} className={i % 2 === 0 ? '' : 'bg-stripe'}>
                  <td className="px-2 py-1 text-text truncate max-w-[140px]">{r.label}</td>
                  <td className="px-2 py-1 text-right text-text">{formatNumber(r.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    }

    // default: bar
    return (
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={preview.rows} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
          <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} angle={-25} textAnchor="end" height={40} />
          <YAxis tick={{ fontSize: 10 }} tickFormatter={formatNumber} width={45} />
          <Tooltip formatter={(v) => (typeof v === 'number' ? formatNumber(v) : v)} />
          <Bar dataKey="value" fill="#6366f1" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    )
  }

  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-surface border-b border-border">
        <span className="text-sm font-medium text-text truncate flex-1 mr-2">{chart.title}</span>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => setPreviewKey((k) => k + 1)}
            className="p-1 text-text-muted hover:text-text rounded transition-colors"
            title="Refresh preview"
          >
            <RefreshCw size={13} />
          </button>
          <button
            onClick={() => setEditOpen((v) => !v)}
            className="p-1 text-text-muted hover:text-text rounded transition-colors"
            title="Edit chart"
          >
            {editOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          <button
            onClick={onRemove}
            className="p-1 text-text-muted hover:text-error rounded transition-colors"
            title="Remove chart"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {/* Edit panel */}
      {editOpen && (
        <div className="px-3 py-2 bg-surface border-b border-border space-y-2 text-xs">
          <div>
            <label className="text-text-muted block mb-1">Title</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-bg border border-border rounded px-2 py-1 text-text focus:outline-none focus:border-accent"
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-text-muted block mb-1">Chart type</label>
              <select
                value={vizType}
                onChange={(e) => setVizType(e.target.value)}
                className="w-full bg-bg border border-border rounded px-2 py-1 text-text focus:outline-none focus:border-accent"
              >
                {VIZ_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-text-muted block mb-1">Metric column</label>
              <select
                value={metricCol}
                onChange={(e) => setMetricCol(e.target.value)}
                className="w-full bg-bg border border-border rounded px-2 py-1 text-text focus:outline-none focus:border-accent"
              >
                <option value="">— select —</option>
                {numericCols.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="text-text-muted block mb-1">Aggregate</label>
              <select
                value={aggregate}
                onChange={(e) => setAggregate(e.target.value)}
                className="w-full bg-bg border border-border rounded px-2 py-1 text-text focus:outline-none focus:border-accent"
              >
                {AGG_OPTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            </div>
            <div>
              <label className="text-text-muted block mb-1">Dimension</label>
              <select
                value={dimensionCol}
                onChange={(e) => setDimensionCol(e.target.value)}
                className="w-full bg-bg border border-border rounded px-2 py-1 text-text focus:outline-none focus:border-accent"
              >
                <option value="">— none —</option>
                {dimCols.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            {timeCols.length > 0 && (
              <>
                <div>
                  <label className="text-text-muted block mb-1">Time column</label>
                  <select
                    value={timeCol}
                    onChange={(e) => setTimeCol(e.target.value)}
                    className="w-full bg-bg border border-border rounded px-2 py-1 text-text focus:outline-none focus:border-accent"
                  >
                    <option value="">— none —</option>
                    {timeCols.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-text-muted block mb-1">Time grain</label>
                  <select
                    value={timeGrain}
                    onChange={(e) => setTimeGrain(e.target.value)}
                    className="w-full bg-bg border border-border rounded px-2 py-1 text-text focus:outline-none focus:border-accent"
                  >
                    <option value="P1D">Day</option>
                    <option value="P1W">Week</option>
                    <option value="P1M">Month</option>
                    <option value="P1Y">Year</option>
                  </select>
                </div>
              </>
            )}
          </div>
          <button
            onClick={handleApply}
            className="w-full bg-accent text-white text-xs rounded px-3 py-1.5 hover:opacity-90 transition-opacity"
          >
            Apply &amp; refresh
          </button>
        </div>
      )}

      {/* Chart */}
      <div className="p-2 flex-1">{renderChart()}</div>
    </div>
  )
}
