/** Interrupteur accessible (role=switch) : clic, Espace et Entrée basculent. */
export function Switch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-8 w-[52px] flex-none rounded-full border-0 p-0 transition-colors disabled:opacity-40 ${checked ? 'bg-night' : 'bg-[#c4c7cc]'}`}
    >
      <span className={`absolute top-1 left-1 block h-6 w-6 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-5' : ''}`} />
    </button>
  )
}
