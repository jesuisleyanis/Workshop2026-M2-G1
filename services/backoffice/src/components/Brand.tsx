import logoMark from '../assets/logo-mark.png'

// Marque « Résilience » — copie de celle du front (logo en masque CSS, couleur = currentColor).
export function Brand({ inverted = false }: { inverted?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <div
        className={`grid h-8 w-8 place-items-center rounded-[10px] ${inverted ? 'bg-[#f3f4f6] text-night' : 'bg-night text-white'}`}
        aria-hidden
      >
        <span className="h-[15px] w-5 bg-current" style={{ mask: `url(${logoMark}) center / contain no-repeat` }} />
      </div>
      <span className="text-[17px] font-semibold tracking-tight">Résilience</span>
    </div>
  )
}
