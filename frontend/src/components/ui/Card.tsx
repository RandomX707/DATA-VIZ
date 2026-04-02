import { clsx } from 'clsx'

interface CardProps {
  children: React.ReactNode
  title?: string
  className?: string
  headerRight?: React.ReactNode
}

export function Card({ children, title, className, headerRight }: CardProps) {
  return (
    <div
      className={clsx(
        'rounded-xl border border-border bg-card',
        className
      )}
    >
      {title && (
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h3 className="text-sm font-semibold text-text">{title}</h3>
          {headerRight}
        </div>
      )}
      {children}
    </div>
  )
}
