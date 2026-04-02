import { useState, useEffect } from 'react'
import {
  BarChart2,
  Layout,
  CheckCircle2,
  XCircle,
  ExternalLink,
  Info,
  Play,
  Hammer,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'sonner'
import { useAppStore } from '../../store/appStore'
import { useSSE } from '../../hooks/useSSE'
import { Button } from '../ui/Button'
import { Input, Textarea } from '../ui/Input'
import { Card } from '../ui/Card'
import { Badge } from '../ui/Badge'
import { ProgressLog } from '../ui/ProgressLog'
import type { DashboardPlan, QAReport } from '../../types'

const VIZ_ICONS: Record<string, string> = {
  big_number_total: '🔢',
  echarts_timeseries_line: '📈',
  bar: '📊',
  dist_bar: '📊',
  pie: '🥧',
  table: '🗂️',
  echarts_scatter: '⚡',
  scatter: '⚡',
}

function VizBadge({ vizType }: { vizType: string }) {
  const icon = VIZ_ICONS[vizType] ?? '📉'
  return (
    <Badge variant="accent">
      {icon} {vizType}
    </Badge>
  )
}

interface PlanTableProps {
  plan: DashboardPlan
}

function PlanTable({ plan }: PlanTableProps) {
  return (
    <div className="space-y-4">
      {/* Charts */}
      <Card title={`Charts (${plan.charts.length})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-surface">
                {['Title', 'Viz Type', 'Width', 'Columns', 'Reasoning'].map(
                  (h) => (
                    <th
                      key={h}
                      className="px-3 py-2 text-left font-medium text-text-muted"
                    >
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {plan.charts.map((chart, i) => {
                const metricCols = chart.metrics.map((m) => {
                  const metric = m as Record<string, unknown>
                  const col = metric['column'] as Record<string, unknown> | undefined
                  return (col?.['column_name'] as string) ?? ''
                }).filter(Boolean)

                const cols = [
                  ...chart.groupby,
                  ...(chart.time_column ? [chart.time_column] : []),
                  ...metricCols,
                ]
                return (
                  <tr
                    key={i}
                    className={
                      i % 2 === 0
                        ? 'border-b border-border/50 bg-card'
                        : 'border-b border-border/50 bg-stripe'
                    }
                  >
                    <td className="px-3 py-2 font-medium text-text">
                      {chart.title}
                    </td>
                    <td className="px-3 py-2">
                      <VizBadge vizType={chart.viz_type} />
                    </td>
                    <td className="px-3 py-2 text-text-muted">
                      {chart.width}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        {[...new Set(cols)].map((c) => (
                          <span
                            key={c}
                            className="rounded bg-border px-1.5 py-0.5 font-mono text-[10px] text-text-muted"
                          >
                            {c}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-text-muted max-w-[180px]">
                      {chart.reasoning}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Filters */}
      {plan.filters.length > 0 && (
        <Card title={`Filters (${plan.filters.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-surface">
                  {['Column', 'Type', 'Label', 'Default'].map((h) => (
                    <th
                      key={h}
                      className="px-3 py-2 text-left font-medium text-text-muted"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {plan.filters.map((f, i) => (
                  <tr
                    key={i}
                    className={
                      i % 2 === 0
                        ? 'border-b border-border/50 bg-card'
                        : 'border-b border-border/50 bg-stripe'
                    }
                  >
                    <td className="px-3 py-2 font-mono text-text">
                      {f.column_name}
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant="muted">{f.filter_type}</Badge>
                    </td>
                    <td className="px-3 py-2 text-text-muted">{f.label}</td>
                    <td className="px-3 py-2 font-mono text-text-dim">
                      {f.default_value ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}

export function Phase3() {
  const { sessionId, phase3, setPhase3, phase2, fetchAuditLog } = useAppStore()

  const planSSE = useSSE()
  const buildSSE = useSSE()

  const [datasetName, setDatasetName] = useState(
    phase3.datasetName || phase2.queryPlan?.dataset_name_suggestion || ''
  )
  const [dashboardTitle, setDashboardTitle] = useState(
    phase3.dashboardTitle || ''
  )
  const [requirements, setRequirements] = useState(phase3.requirements || '')
  const [dashboardId, setDashboardId] = useState('')
  const [dryRun, setDryRun] = useState(false)

  const dashboardPlan = phase3.dashboardPlan as DashboardPlan | null
  const qaReport = phase3.qaReport as QAReport | null

  // On plan SSE done — store result
  useEffect(() => {
    if (planSSE.isDone && planSSE.result && !phase3.planReady) {
      const data = planSSE.result as { dashboard_plan: DashboardPlan }
      setPhase3({
        dashboardPlan: data.dashboard_plan,
        planReady: true,
        datasetName,
        dashboardTitle,
        requirements,
      })
      void fetchAuditLog()
    }
  }, [planSSE.isDone, planSSE.result, phase3.planReady, setPhase3, datasetName, dashboardTitle, requirements, fetchAuditLog])

  // On build SSE done — store result
  useEffect(() => {
    if (buildSSE.isDone && buildSSE.result) {
      const data = buildSSE.result as {
        dashboard_url: string | null
        qa_report: QAReport | null
      }
      setPhase3({
        dashboardUrl: data.dashboard_url ?? null,
        qaReport: data.qa_report ?? null,
      })
      if (data.dashboard_url) {
        toast.success('Dashboard built successfully!')
      }
      void fetchAuditLog()
    }
  }, [buildSSE.isDone, buildSSE.result, setPhase3, fetchAuditLog])

  function handlePlan() {
    if (!sessionId) return
    planSSE.reset()
    setPhase3({ planReady: false, dashboardPlan: null, dashboardUrl: null })
    const qs = new URLSearchParams({
      dataset_name: datasetName,
      dashboard_title: dashboardTitle,
      requirements,
    }).toString()
    planSSE.start(`/api/sessions/${sessionId}/phase3/plan?${qs}`)
  }

  function handleBuild() {
    if (!sessionId) return
    buildSSE.reset()
    setPhase3({ dashboardUrl: null, qaReport: null })
    const qs = new URLSearchParams()
    if (dashboardId) qs.set('dashboard_id', dashboardId)
    qs.set('dry_run', String(dryRun))
    buildSSE.start(
      `/api/sessions/${sessionId}/phase3/build?${qs.toString()}`
    )
  }

  return (
    <div className="flex flex-col gap-6 p-6 max-w-4xl w-full mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-text">Dashboard Builder</h1>
        <p className="mt-1 text-sm text-text-muted">
          Plan and build your Superset dashboard from a dataset.
        </p>
      </div>

      {/* Input form */}
      <Card>
        <div className="p-4 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Dataset Name"
              value={datasetName}
              onChange={(e) => setDatasetName(e.target.value)}
              placeholder="my_dataset_name"
            />
            <Input
              label="Dashboard Title"
              value={dashboardTitle}
              onChange={(e) => setDashboardTitle(e.target.value)}
              placeholder="Sales Performance Dashboard"
            />
          </div>
          <Textarea
            label="Requirements"
            rows={5}
            value={requirements}
            onChange={(e) => setRequirements(e.target.value)}
            placeholder={[
              'Describe the charts and filters you want. e.g.:',
              '- Show total revenue as a headline number',
              '- Line chart of revenue by month',
              '- Bar chart of top 10 customers by revenue',
              '- Filter by region and date range',
            ].join('\n')}
          />
          <div className="flex items-end gap-4">
            <div className="max-w-[200px]">
              <Input
                label="Dashboard ID (optional, for update mode)"
                value={dashboardId}
                onChange={(e) => setDashboardId(e.target.value)}
                placeholder="42"
              />
            </div>
            <label className="flex items-center gap-2 cursor-pointer mb-0.5">
              <div
                className={`relative h-5 w-9 rounded-full transition-colors cursor-pointer ${
                  dryRun ? 'bg-accent' : 'bg-border'
                }`}
                onClick={() => setDryRun((d) => !d)}
              >
                <div
                  className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                    dryRun ? 'translate-x-4' : 'translate-x-0.5'
                  }`}
                />
              </div>
              <span className="text-sm text-text-muted">Dry Run</span>
            </label>
          </div>
          <Button
            variant="primary"
            icon={<Layout size={15} />}
            loading={planSSE.isStreaming}
            disabled={!datasetName.trim() || !dashboardTitle.trim() || !requirements.trim()}
            onClick={handlePlan}
          >
            {planSSE.isStreaming ? 'Planning...' : 'Plan Dashboard'}
          </Button>
        </div>
      </Card>

      {/* Plan progress */}
      <ProgressLog
        logs={planSSE.logs}
        isStreaming={planSSE.isStreaming}
        isDone={planSSE.isDone}
        error={planSSE.error}
      />

      {/* Plan results */}
      <AnimatePresence>
        {dashboardPlan && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-5"
          >
            {/* Plan reasoning */}
            <div className="flex items-start gap-3 rounded-xl border border-border bg-card p-4">
              <BarChart2 size={16} className="text-accent mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-semibold text-text mb-1">
                  {dashboardPlan.dashboard_title}
                </p>
                <p className="text-xs text-text-muted">{dashboardPlan.reasoning}</p>
              </div>
            </div>

            {/* Dry run banner */}
            {dryRun && (
              <div className="flex items-center gap-2 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3">
                <Info size={15} className="text-warning shrink-0" />
                <p className="text-sm text-warning">
                  Dry Run mode: plan only, no changes will be made in Superset.
                </p>
              </div>
            )}

            <PlanTable plan={dashboardPlan} />

            {/* Build button */}
            {!dryRun && (
              <div className="flex items-center gap-3">
                <Button
                  variant="success"
                  icon={<Hammer size={15} />}
                  loading={buildSSE.isStreaming}
                  onClick={handleBuild}
                >
                  {buildSSE.isStreaming ? 'Building...' : 'Build in Superset'}
                </Button>
                <Button
                  variant="secondary"
                  icon={<Play size={14} />}
                  onClick={handlePlan}
                >
                  Re-plan
                </Button>
              </div>
            )}

            {/* Build progress */}
            <ProgressLog
              logs={buildSSE.logs}
              isStreaming={buildSSE.isStreaming}
              isDone={buildSSE.isDone}
              error={buildSSE.error}
            />

            {/* Build results */}
            <AnimatePresence>
              {phase3.dashboardUrl && (
                <motion.div
                  initial={{ opacity: 0, scale: 0.97 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="space-y-4"
                >
                  {/* Success card */}
                  <div className="flex items-center gap-3 rounded-xl border border-success/30 bg-success/10 p-4">
                    <CheckCircle2 size={20} className="text-success shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-success">
                        Dashboard built successfully!
                      </p>
                      <p className="mt-0.5 text-xs text-text-muted font-mono truncate">
                        {phase3.dashboardUrl}
                      </p>
                    </div>
                    <a
                      href={phase3.dashboardUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <Button
                        variant="success"
                        size="sm"
                        icon={<ExternalLink size={13} />}
                      >
                        Open Dashboard
                      </Button>
                    </a>
                  </div>

                  {/* QA report */}
                  {qaReport && (
                    <Card title="QA Report">
                      <div className="p-4 space-y-3">
                        <div className="flex items-center gap-2">
                          {qaReport.passed ? (
                            <>
                              <CheckCircle2 size={16} className="text-success" />
                              <span className="text-sm font-semibold text-success">
                                All checks passed
                              </span>
                            </>
                          ) : (
                            <>
                              <XCircle size={16} className="text-error" />
                              <span className="text-sm font-semibold text-error">
                                Issues found
                              </span>
                            </>
                          )}
                        </div>
                        {qaReport.issues.length > 0 && (
                          <div>
                            <p className="text-xs font-medium text-text-muted mb-1">
                              Issues:
                            </p>
                            <ul className="space-y-1">
                              {qaReport.issues.map((issue, i) => (
                                <li key={i} className="text-xs text-error">
                                  • {issue}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {qaReport.suggestions.length > 0 && (
                          <div>
                            <p className="text-xs font-medium text-text-muted mb-1">
                              Suggestions:
                            </p>
                            <ul className="space-y-1">
                              {qaReport.suggestions.map((s, i) => (
                                <li key={i} className="text-xs text-warning">
                                  → {s}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    </Card>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
