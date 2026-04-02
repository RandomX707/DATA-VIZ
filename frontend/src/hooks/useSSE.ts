import { useState, useCallback, useRef, useEffect } from 'react'
import type { SSEEvent } from '../types'

interface LogEntry {
  message: string
  timestamp: string
}

interface UseSSEReturn {
  logs: LogEntry[]
  isStreaming: boolean
  isDone: boolean
  error: string | null
  result: unknown
  start: (url: string) => void
  reset: () => void
  stop: () => void
}

export function useSSE(): UseSSEReturn {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [isDone, setIsDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<unknown>(null)

  // Keep a ref so we can always close the current connection
  const esRef = useRef<EventSource | null>(null)

  // Close and null the ref
  const close = useCallback(() => {
    if (esRef.current) {
      esRef.current.onmessage = null
      esRef.current.onerror = null
      esRef.current.close()
      esRef.current = null
    }
  }, [])

  // Clean up on unmount
  useEffect(() => () => close(), [close])

  const reset = useCallback(() => {
    close()
    setLogs([])
    setIsStreaming(false)
    setIsDone(false)
    setError(null)
    setResult(null)
  }, [close])

  const stop = useCallback(() => {
    close()
    setIsStreaming(false)
  }, [close])

  const start = useCallback(
    (url: string): void => {
      // Close any existing connection first
      close()

      setLogs([])
      setIsStreaming(true)
      setIsDone(false)
      setError(null)
      setResult(null)

      const es = new EventSource(url)
      esRef.current = es

      es.onmessage = (e: MessageEvent) => {
        // Guard: ignore events from a stale connection
        if (esRef.current !== es) return

        try {
          const event: SSEEvent = JSON.parse(e.data as string)

          if (event.type === 'progress') {
            setLogs((prev) => [
              ...prev,
              {
                message: event.message ?? '',
                timestamp: new Date().toLocaleTimeString(),
              },
            ])
          } else if (event.type === 'done') {
            setIsStreaming(false)
            setIsDone(true)
            setResult(event.data)
            close()
          } else if (event.type === 'error') {
            setIsStreaming(false)
            setError(event.message ?? 'Unknown error')
            close()
          }
        } catch {
          // ignore parse errors
        }
      }

      es.onerror = () => {
        // Guard: ignore errors from stale connections
        if (esRef.current !== es) return
        setIsStreaming(false)
        setError('Connection error')
        close()
      }
    },
    [close]
  )

  return { logs, isStreaming, isDone, error, result, start, reset, stop }
}
