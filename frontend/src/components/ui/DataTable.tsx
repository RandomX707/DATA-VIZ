import { clsx } from 'clsx'

interface DataTableProps {
  columns: string[]
  rows: Record<string, unknown>[]
  className?: string
  maxRows?: number
}

export function DataTable({ columns, rows, className, maxRows }: DataTableProps) {
  const displayRows = maxRows ? rows.slice(0, maxRows) : rows

  return (
    <div className={clsx('overflow-x-auto rounded-lg border border-border', className)}>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border bg-surface">
            {columns.map((col) => (
              <th
                key={col}
                className="px-3 py-2 text-left font-medium text-text-muted"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {displayRows.map((row, i) => (
            <tr
              key={i}
              className={clsx(
                'border-b border-border/50 last:border-0',
                i % 2 === 0 ? 'bg-card' : 'bg-stripe'
              )}
            >
              {columns.map((col) => (
                <td key={col} className="px-3 py-2 font-mono text-text-muted">
                  {String(row[col] ?? '')}
                </td>
              ))}
            </tr>
          ))}
          {displayRows.length === 0 && (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-6 text-center text-text-muted"
              >
                No data
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
