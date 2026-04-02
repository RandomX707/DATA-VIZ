import { useState } from 'react'
import { X, Download, Trash2 } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'sonner'
import { useAppStore } from '../../store/appStore'
import { clearAuditLog } from '../../api/client'
import type { AuditEntry } from '../../types'

// ── StatusDot ─────────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  success: '#1D9E75',
  warning: '#BA7517',
  error: '#E24B4A',
  info: '#64748b',
}

function StatusDot({
  status,
  size = 'sm',
}: {
  status: string
  size?: 'sm' | 'md'
}) {
  const px = size === 'md' ? 10 : 7
  return (
    <span
      style={{
        display: 'inline-block',
        width: px,
        height: px,
        borderRadius: '50%',
        backgroundColor: STATUS_COLORS[status] ?? STATUS_COLORS.info,
        flexShrink: 0,
      }}
    />
  )
}

// ── PhaseBadge ────────────────────────────────────────────────────────────────

const PHASE_STYLES: Record<number, { bg: string; color: string; label: string }> = {
  1: { bg: 'rgba(20,184,166,0.15)', color: '#14b8a6', label: 'P1' },
  2: { bg: 'rgba(139,92,246,0.15)', color: '#8b5cf6', label: 'P2' },
  3: { bg: 'rgba(249,115,22,0.15)', color: '#f97316', label: 'P3' },
  0: { bg: 'rgba(100,116,139,0.15)', color: '#64748b', label: 'SYS' },
}

function PhaseBadge({ phase }: { phase: number }) {
  const style = PHASE_STYLES[phase] ?? PHASE_STYLES[0]
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '1px 6px',
        borderRadius: 4,
        fontSize: 10,
        fontWeight: 600,
        backgroundColor: style.bg,
        color: style.color,
        flexShrink: 0,
      }}
    >
      {style.label}
    </span>
  )
}

// ── AuditEntryRow ─────────────────────────────────────────────────────────────

function AuditEntryRow({
  entry,
  isLast,
}: {
  entry: AuditEntry
  isLast: boolean
}) {
  return (
    <div className="flex gap-3">
      {/* Timeline connector */}
      <div className="flex flex-col items-center">
        <StatusDot status={entry.status} size="md" />
        {!isLast && (
          <div
            className="mt-1 w-px flex-1 bg-border"
            style={{ minHeight: 16 }}
          />
        )}
      </div>

      {/* Content */}
      <div className="pb-4 flex-1 min-w-0">
        {/* Header row */}
        <div className="flex items-center gap-2 flex-wrap mb-0.5">
          <span className="text-sm font-semibold text-text">{entry.title}</span>
          <PhaseBadge phase={entry.phase} />
          <span className="text-xs text-text-dim ml-auto shrink-0">
            {new Date(entry.timestamp).toLocaleTimeString()}
          </span>
        </div>

        {/* Detail */}
        <p className="text-xs text-text-muted leading-relaxed">{entry.detail}</p>

        {/* Expandable data */}
        {entry.data && (
          <details className="mt-1.5">
            <summary className="text-xs text-text-dim cursor-pointer hover:text-text-muted transition-colors select-none">
              Details
            </summary>
            <pre
              className="mt-1 rounded bg-surface px-3 py-2 text-[11px] font-mono text-text-muted overflow-x-auto"
              style={{ maxHeight: 200 }}
            >
              {JSON.stringify(entry.data, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </div>
  )
}

// ── Export helper (shared) ────────────────────────────────────────────────────

export function exportAuditJSON(entries: AuditEntry[]) {
  const blob = new Blob(
    [JSON.stringify({ entries }, null, 2)],
    { type: 'application/json' }
  )
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `audit_log_${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

// ── AuditPanel ────────────────────────────────────────────────────────────────

type FilterValue = 'all' | 1 | 2 | 3

export function AuditPanel() {
  const {
    sessionId,
    auditEntries,
    auditPanelOpen,
    setAuditEntries,
    setAuditPanelOpen,
  } = useAppStore()

  const [filter, setFilter] = useState<FilterValue>('all')

  const filteredEntries =
    filter === 'all'
      ? auditEntries
      : auditEntries.filter((e) => e.phase === filter)

  async function handleClearLog() {
    if (!sessionId) return
    try {
      await clearAuditLog(sessionId)
      setAuditEntries([])
      toast.success('Audit log cleared')
    } catch {
      toast.error('Failed to clear audit log')
    }
  }


  return (
    <AnimatePresence>
      {auditPanelOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            key="audit-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 bg-black/30 z-40"
            onClick={() => setAuditPanelOpen(false)}
          />

          {/* Panel */}
          <motion.div
            key="audit-panel"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'tween', duration: 0.2 }}
            style={{
              position: 'fixed',
              top: 0,
              right: 0,
              width: 'min(560px, 100vw)',
              height: '100vh',
              zIndex: 50,
              background: 'var(--color-card)',
              borderLeft: '0.5px solid var(--color-border)',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            {/* Header */}
            <div
              className="flex items-center gap-3 px-5 py-4 border-b border-border shrink-0"
            >
              <h2 className="text-base font-bold text-text flex-1">Audit Log</h2>
              <span className="text-xs text-text-dim">
                {auditEntries.length} events
              </span>
              <button
                onClick={() => setAuditPanelOpen(false)}
                className="rounded p-1 hover:bg-surface transition-colors text-text-muted hover:text-text"
              >
                <X size={16} />
              </button>
            </div>

            {/* Filter bar */}
            <div className="flex gap-1 px-5 py-3 border-b border-border shrink-0">
              {(['all', 1, 2, 3] as const).map((f) => (
                <button
                  key={String(f)}
                  onClick={() => setFilter(f)}
                  className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                    filter === f
                      ? 'bg-accent text-white'
                      : 'text-text-muted hover:text-text hover:bg-surface'
                  }`}
                >
                  {f === 'all' ? 'All' : `Phase ${f}`}
                </button>
              ))}
              <span className="ml-auto text-xs text-text-dim self-center">
                {filteredEntries.length} shown
              </span>
            </div>

            {/* Timeline */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {filteredEntries.length === 0 ? (
                <p className="text-sm text-text-dim text-center mt-8">
                  No events yet
                </p>
              ) : (
                filteredEntries.map((entry, i) => (
                  <AuditEntryRow
                    key={entry.id}
                    entry={entry}
                    isLast={i === filteredEntries.length - 1}
                  />
                ))
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center gap-2 px-5 py-3 border-t border-border shrink-0">
              <button
                onClick={() => exportAuditJSON(auditEntries)}
                className="flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium text-text-muted hover:text-text hover:bg-surface transition-colors"
              >
                <Download size={13} />
                Export JSON
              </button>
              <button
                onClick={handleClearLog}
                className="flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium text-error/70 hover:text-error hover:bg-error/10 transition-colors ml-auto"
              >
                <Trash2 size={13} />
                Clear log
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
