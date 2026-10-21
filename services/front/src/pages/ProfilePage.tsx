import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon } from '../components/icons'
import { SERVICES } from '../components/Layout'
import { ConfirmDialog } from '../components/ui'
import { useAuth } from '../hooks/useAuth'
import { useBankData } from '../hooks/useBankData'
import { formatClock, sessionPct, useSecondsLeft } from '../hooks/useSecondsLeft'
import { avatarTone, initials } from '../lib/bank'

export function ProfilePage() {
  const { username, expiresAt, logout } = useAuth()
  const { accounts, beneficiaries, limits } = useBankData()
  const navigate = useNavigate()
  const left = useSecondsLeft(expiresAt)
  const [confirm, setConfirm] = useState(false)
  const name = username ?? 'Client'
  const plural = (n: number, word: string) => `${n} ${word}${n > 1 ? 's' : ''}`
  const subs: Record<string, string> = {
    '/rib': plural(accounts.data?.length ?? 0, 'compte'),
    '/beneficiaries': plural(beneficiaries.data?.length ?? 0, 'bénéficiaire'),
    // Libellé fixe : pas de GET /api/v1/cards à chaque ouverture du Profil (écran Cartes seul).
    '/cards': 'Geler, plafond de paiement',
    '/scheduled': 'Unique, hebdomadaire ou mensuel',
    '/limits': limits.data ? (limits.data.some((l) => l.limit !== null) ? 'Plafond mensuel' : 'Sans plafond') : limits.error ? 'Indisponible pour le moment' : '',
  }

  return (
    <div className="mx-auto flex w-full max-w-[620px] flex-col gap-4">
      <section className="card flex flex-row items-center gap-4 p-[22px]">
        <span className="grid h-[72px] w-[72px] flex-none place-items-center rounded-full bg-night text-2xl font-semibold text-white">{initials(name)}</span>
        <div className="flex flex-1 flex-col gap-0.5">
          <span className="text-xl font-bold">{name}</span>
          <span className="font-mono text-sm text-ink-3">Espace client</span>
        </div>
      </section>
      {left !== null && (
        <section className="flex items-center gap-3.5 rounded-3xl bg-night px-5 py-[18px] text-white">
          <span className="text-ink-4">
            <Icon name="clock" />
          </span>
          <div className="flex flex-1 flex-col gap-2">
            <span className="flex justify-between text-sm text-ink-4">
              Session restante
              <span className="tnum text-lg font-bold text-white">{formatClock(left)}</span>
            </span>
            <span className="block h-1.5 overflow-hidden rounded-full bg-[#3a3d44]">
              <span className="block h-full rounded-full bg-white" style={{ width: sessionPct(left) }} />
            </span>
          </div>
        </section>
      )}
      <nav aria-label="Services" className="rounded-3xl bg-white p-1.5 shadow-card">
        {SERVICES.map((s, i) => {
          const [bg, ink] = avatarTone(i)
          return (
            <button key={s.path} type="button" onClick={() => navigate(s.path)} className="flex min-h-[60px] w-full items-center gap-3.5 rounded-2xl border-0 bg-transparent px-2.5 py-2 text-left hover:bg-page">
              <span className="grid h-10 w-10 flex-none place-items-center rounded-xl" style={{ background: bg, color: ink }}>
                <Icon name={s.icon} />
              </span>
              <span className="flex flex-1 flex-col">
                <span className="text-[15px] font-semibold">{s.label}</span>
                <span className="text-[13px] text-ink-3">{subs[s.path]}</span>
              </span>
              <span className="text-ink-3">
                <Icon name="chev" />
              </span>
            </button>
          )
        })}
      </nav>
      <button type="button" onClick={() => setConfirm(true)} className="btn-ghost text-ko-fg">
        <Icon name="logout" />
        Se déconnecter
      </button>
      {confirm && (
        <ConfirmDialog
          title="Se déconnecter ?"
          text="Vous devrez saisir à nouveau votre identifiant et votre mot de passe."
          confirmLabel="Se déconnecter"
          icon="logout"
          onConfirm={() => logout('manual')}
          onCancel={() => setConfirm(false)}
        />
      )}
    </div>
  )
}
