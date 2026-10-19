import type { ReactNode } from 'react'

interface Props {
  title: string
  children: ReactNode
  className?: string
  aside?: ReactNode
}

/** Carte de base : titre en capitales, contraste élevé. */
export function Panel({ title, children, className = '', aside }: Props) {
  return (
    <section aria-label={title} className={`rounded-2xl border border-slate-800 bg-slate-900/70 p-6 ${className}`}>
      <header className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-400">{title}</h2>
        {aside}
      </header>
      {children}
    </section>
  )
}
