import { useId, useState, type FormEvent } from 'react'

interface Props {
  /** Jeton saisi (non vide) ; l'appelant le mémorise et rejoue l'action. */
  onSubmit: (token: string) => void
  onCancel: () => void
  /** Action en attente, rappelée à l'opérateur. */
  action: string
}

/**
 * Saisie du jeton opérateur (REMEDIATION_OPERATOR_TOKEN) au premier usage d'une écriture.
 * Champ masqué (démo projetée), jamais d'autocomplétion : le jeton ne quitte pas sessionStorage.
 */
export function OperatorTokenForm({ onSubmit, onCancel, action }: Props) {
  const [token, setToken] = useState('')
  const id = useId()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (token.trim()) onSubmit(token.trim())
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-2 rounded-xl border border-edge bg-card-2 px-3.5 py-3 text-[13px]">
      <label htmlFor={id} className="text-xs text-mute-2">
        Jeton opérateur requis pour : {action}
      </label>
      <input
        id={id}
        type="password"
        autoComplete="off"
        spellCheck={false}
        value={token}
        onChange={(e) => setToken(e.target.value)}
        className="h-[30px] rounded-lg border border-edge bg-card px-3 font-mono text-[13px]"
        autoFocus
      />
      <span className="flex gap-2">
        <button type="submit" disabled={!token.trim()} className="h-[26px] cursor-pointer rounded-full border border-[#333339] px-2.5 text-xs hover:bg-[#1b1b1e] disabled:opacity-50">
          Valider
        </button>
        <button type="button" onClick={onCancel} className="h-[26px] cursor-pointer rounded-full border border-[#333339] px-2.5 text-xs hover:bg-[#1b1b1e]">
          Annuler
        </button>
      </span>
    </form>
  )
}
