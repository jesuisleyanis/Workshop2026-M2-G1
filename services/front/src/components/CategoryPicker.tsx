import { useRef, type KeyboardEvent } from 'react'
import { Icon } from './icons'
import { CATEGORIES } from '../lib/categories'
import type { Category } from '../types/api'

/**
 * Sélecteur de catégorie (maquette D8) : pastilles `aria-pressed`, réutilisé par Envoyer et les filtres.
 * `allLabel` ajoute une pastille « toutes » (valeur null) pour un filtre. Flèches gauche/droite = pastille voisine.
 */
export function CategoryPicker({
  label,
  value,
  onChange,
  allLabel,
  wrap = false,
}: {
  label: string
  value: Category | null
  onChange: (c: Category | null) => void
  allLabel?: string
  wrap?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  const options: { id: Category | null; label: string; icon: (typeof CATEGORIES)[number]['icon'] | null }[] = [
    ...(allLabel ? [{ id: null, label: allLabel, icon: null }] : []),
    ...CATEGORIES.map((c) => ({ id: c.id, label: c.label, icon: c.icon })),
  ]

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    const buttons = Array.from(ref.current?.querySelectorAll('button') ?? [])
    const i = buttons.indexOf(document.activeElement as HTMLButtonElement)
    if (i < 0) return
    e.preventDefault()
    buttons[(i + (e.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length]?.focus()
  }

  return (
    <div ref={ref} role="group" aria-label={label} onKeyDown={onKey} className={`flex gap-2 ${wrap ? 'flex-wrap' : '-mx-0.5 overflow-x-auto px-0.5 pb-1'}`}>
      {options.map((o) => {
        const on = o.id === value
        return (
          <button
            key={o.id ?? 'all'}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(o.id)}
            className={`flex min-h-10 flex-none items-center gap-1.5 rounded-full border-[1.5px] px-3.5 text-[13px] font-semibold whitespace-nowrap ${on ? 'border-ink bg-night text-white' : 'border-line bg-white text-ink'}`}
          >
            {o.icon && <Icon name={o.icon} size={16} />}
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
