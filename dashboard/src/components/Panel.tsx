import type { ReactNode } from 'react'

export type Tone = 'ok' | 'warn' | 'ko' | 'mute' | 'accent' | 'info'

/** Couleur de texte + fond translucide par tonalité (pastilles, points, barres). */
export const TONE: Record<Tone, { text: string; bg: string; solid: string; border: string }> = {
  ok: { text: 'text-ok', bg: 'bg-ok/12', solid: 'bg-ok', border: 'border-ok/35' },
  warn: { text: 'text-warn', bg: 'bg-warn/12', solid: 'bg-warn', border: 'border-warn/35' },
  ko: { text: 'text-ko', bg: 'bg-ko/12', solid: 'bg-ko', border: 'border-ko/35' },
  mute: { text: 'text-mute-2', bg: 'bg-mute-2/12', solid: 'bg-mute-3', border: 'border-edge' },
  accent: { text: 'text-accent-2', bg: 'bg-accent/14', solid: 'bg-accent', border: 'border-accent' },
  info: { text: 'text-info', bg: 'bg-info/12', solid: 'bg-info', border: 'border-info/35' },
}

export function Pill({ tone, children, className = '' }: { tone: Tone; children: ReactNode; className?: string }) {
  const t = TONE[tone]
  return <span className={`whitespace-nowrap rounded-[7px] px-2 py-[3px] text-xs ${t.bg} ${t.text} ${className}`}>{children}</span>
}

interface Props {
  title: string
  children: ReactNode
  className?: string
  aside?: ReactNode
  subtitle?: ReactNode
}

/** Carte de base de la console : titre, sous-titre optionnel, élément à droite. */
export function Panel({ title, children, className = '', aside, subtitle }: Props) {
  return (
    <section aria-label={title} className={`card gap-3.5 ${className}`}>
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 className="text-[17px] font-medium">{title}</h2>
          {subtitle && <span className="text-xs text-mute-2">{subtitle}</span>}
        </div>
        {aside}
      </header>
      {children}
    </section>
  )
}
