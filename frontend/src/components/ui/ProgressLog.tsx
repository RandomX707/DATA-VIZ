import { useEffect, useRef } from 'react'
import { CheckCircle2, XCircle } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { Spinner } from './Spinner'

interface LogEntry {
  message: string
  timestamp: string
}

interface ProgressLogProps {
  logs: LogEntry[]
  isStreaming: boolean
  isDone: boolean
  error: string | null
}

export function ProgressLog({
  logs,
  isStreaming,
  isDone,
  error,
}: ProgressLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  if (!isStreaming && !isDone && !error && logs.length === 0) return null

  return (
    <div className="rounded-xl border border-border bg-surface p-4 font-mono text-xs">
      <div className="max-h-48 overflow-y-auto space-y-1">
        <AnimatePresence initial={false}>
          {logs.map((log, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-start gap-2"
            >
              <span className="shrink-0 text-text-dim">{log.timestamp}</span>
              <span
                className={
                  i === logs.length - 1 && isStreaming
                    ? 'text-text'
                    : 'text-text-muted'
                }
              >
                {log.message}
              </span>
              {i === logs.length - 1 && isStreaming && (
                <Spinner size={12} className="mt-0.5 shrink-0" />
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        {isDone && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-2 text-success"
          >
            <CheckCircle2 size={13} />
            <span>Done</span>
          </motion.div>
        )}

        {error && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-start gap-2 text-error"
          >
            <XCircle size={13} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </motion.div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}
