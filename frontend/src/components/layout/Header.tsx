import { Check, Sun, Moon } from 'lucide-react'
import { clsx } from 'clsx'
import { useAppStore } from '../../store/appStore'

const STEPS = [
  { label: 'Schema', phase: 1 as const },
  { label: 'Query', phase: 2 as const },
  { label: 'Dashboard', phase: 3 as const },
]

export function Header() {
  const { activePhase, setActivePhase, phase1, phase2, theme, toggleTheme } =
    useAppStore()

  function canNavigateTo(phase: 1 | 2 | 3): boolean {
    if (phase === 1) return true
    if (phase === 2) return phase1.confirmed
    if (phase === 3) return phase2.confirmed
    return false
  }

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-card px-6">
<nav className="flex items-center gap-1">
        {STEPS.map((step, idx) => {
          const isActive = activePhase === step.phase
          const isCompleted =
            (step.phase === 1 && phase1.confirmed) ||
            (step.phase === 2 && phase2.confirmed)
          const isClickable = canNavigateTo(step.phase)

          return (
            <div key={step.phase} className="flex items-center gap-1">
              <button
                className={clsx(
                  'flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition-all',
                  isActive
                    ? 'bg-accent/15 text-accent ring-1 ring-accent/40'
                    : isCompleted
                    ? 'text-success hover:bg-success/10 cursor-pointer'
                    : isClickable
                    ? 'text-text-muted hover:bg-card-hover cursor-pointer'
                    : 'text-text-dim cursor-not-allowed'
                )}
                onClick={() => isClickable && setActivePhase(step.phase)}
                disabled={!isClickable}
              >
                <span
                  className={clsx(
                    'flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold',
                    isActive
                      ? 'bg-accent text-white'
                      : isCompleted
                      ? 'bg-success text-white'
                      : 'bg-border text-text-muted'
                  )}
                >
                  {isCompleted && !isActive ? (
                    <Check size={9} strokeWidth={3} />
                  ) : (
                    step.phase
                  )}
                </span>
                {step.label}
              </button>

              {idx < STEPS.length - 1 && (
                <span className="text-text-dim select-none px-0.5">›</span>
              )}
            </div>
          )
        })}
      </nav>

      {/* Theme toggle */}
      <button
        onClick={toggleTheme}
        title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        className="flex h-8 w-8 items-center justify-center rounded-lg border border-border text-text-muted transition-all hover:bg-card-hover hover:text-text"
      >
        {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
      </button>
    </header>
  )
}
