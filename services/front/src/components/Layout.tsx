import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../hooks/useAuth'
import { useBankData } from '../hooks/useBankData'
import { useIsDesktop } from '../hooks/useMediaQuery'
import { useServiceStatus } from '../hooks/useServiceStatus'
import { formatClock, sessionPct, useSecondsLeft } from '../hooks/useSecondsLeft'
import { ShellContext, type Shell } from '../hooks/shell-context'
import { initials } from '../lib/bank'
import { badgeText, bellLabel } from '../lib/notifications'
import { BankDataProvider } from './BankDataProvider'
import { Icon, type IconName } from './icons'
import { Brand } from './ui'

interface Screen {
  path: string
  label: string
  icon: IconName
  title: string
}

const TABS: Screen[] = [
  { path: '/', label: 'Accueil', icon: 'home', title: 'Accueil' },
  { path: '/stats', label: 'Statistiques', icon: 'chart', title: 'Statistiques' },
  { path: '/send', label: 'Envoyer', icon: 'send', title: 'Envoyer de l’argent' },
  { path: '/history', label: 'Historique', icon: 'history', title: 'Historique' },
  { path: '/profile', label: 'Profil', icon: 'user', title: 'Profil' },
]

/** Services (barre latérale desktop, menu Profil sur mobile). Les autres arrivent avec leurs tickets backend. */
export const SERVICES: Screen[] = [
  { path: '/beneficiaries', label: 'Bénéficiaires', icon: 'user', title: 'Bénéficiaires' },
  { path: '/cards', label: 'Cartes', icon: 'card', title: 'Cartes' },
  { path: '/rib', label: 'RIB', icon: 'bank', title: 'Relevé d’identité bancaire' },
  { path: '/limits', label: 'Plafonds', icon: 'sliders', title: 'Plafonds de virement' },
  { path: '/scheduled', label: 'Virements programmés', icon: 'clock', title: 'Virements programmés' },
]

/** Écrans hors onglets : titre + onglet parent (retour). */
const SUBSCREENS: { prefix: string; title: string; parent: string }[] = [
  { prefix: '/operations/', title: 'Détail de l’opération', parent: '/history' },
  { prefix: '/rib', title: 'Relevé d’identité bancaire', parent: '/profile' },
  { prefix: '/beneficiaries', title: 'Bénéficiaires', parent: '/profile' },
  { prefix: '/limits', title: 'Plafonds de virement', parent: '/profile' },
  { prefix: '/cards', title: 'Cartes', parent: '/profile' },
  { prefix: '/scheduled', title: 'Virements programmés', parent: '/profile' },
  { prefix: '/notifications', title: 'Notifications', parent: '/' },
]

export function Layout() {
  return (
    <BankDataProvider>
      <Shell />
    </BankDataProvider>
  )
}

function Shell() {
  const { username, expiresAt } = useAuth()
  const isDesktop = useIsDesktop()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const mainRef = useRef<HTMLElement>(null)
  // L'id relance l'affichage (et le minuteur) même si le même message est émis deux fois de suite.
  const [toastMsg, setToast] = useState<{ id: number; text: string } | null>(null)
  const [backOverride, setOverride] = useState<(() => void) | null>(null)

  const toast = useCallback((text: string) => setToast((t) => ({ id: (t?.id ?? 0) + 1, text })), [])
  useEffect(() => {
    if (!toastMsg) return
    const id = setTimeout(() => setToast(null), 2400)
    return () => clearTimeout(id)
  }, [toastMsg])
  const setBackOverride = useCallback((fn: (() => void) | null) => setOverride(() => fn), [])
  const shell = useMemo<Shell>(() => ({ isDesktop, toast, setBackOverride }), [isDesktop, toast, setBackOverride])

  useEffect(() => {
    mainRef.current?.scrollTo?.({ top: 0 })
  }, [pathname])

  const tab = TABS.find((t) => t.path === pathname)
  const sub = SUBSCREENS.find((s) => pathname.startsWith(s.prefix))
  const title = tab?.title ?? sub?.title ?? ''
  const activeTab = tab?.path ?? sub?.parent ?? '/'
  const showBack = backOverride !== null || (!tab && !!sub)
  const name = username ?? 'Client'
  const onBack = () => (backOverride ? backOverride() : navigate(sub?.parent ?? '/'))

  return (
    <ShellContext.Provider value={shell}>
      <div className="relative flex h-dvh overflow-hidden bg-page">
        {isDesktop && <Sidebar pathname={pathname} activeTab={activeTab} expiresAt={expiresAt} />}

        <div className="relative flex min-w-0 flex-1 flex-col">
          <header className={`flex flex-none items-center gap-3 ${isDesktop ? 'px-10 pt-[22px] pb-3.5' : 'px-5 pt-3.5 pb-2.5'}`}>
            {showBack && (
              <button type="button" aria-label="Retour" onClick={onBack} className="round-btn">
                <Icon name="back" />
              </button>
            )}
            {pathname === '/' ? (
              <div className="flex min-w-0 flex-1 flex-col leading-[1.15]">
                <span className="text-base text-ink-3">Bonjour</span>
                <h1 className="m-0 truncate text-[28px] font-bold tracking-[-0.03em]">{name}</h1>
              </div>
            ) : (
              <h1 className={`m-0 min-w-0 flex-1 truncate font-semibold tracking-[-0.02em] ${isDesktop ? 'text-[28px]' : 'text-[22px]'}`}>{title}</h1>
            )}
            <Bell onOpen={() => navigate('/notifications')} />
            <button
              type="button"
              aria-label="Profil"
              onClick={() => navigate('/profile')}
              className="grid h-11 w-11 flex-none place-items-center rounded-full border-0 bg-night text-[15px] font-semibold text-white"
            >
              {initials(name)}
            </button>
          </header>

          <ServiceBanner isDesktop={isDesktop} />

          <main ref={mainRef} className={`min-h-0 flex-1 overflow-y-auto ${isDesktop ? 'px-10 pt-2 pb-12' : 'px-5 pt-1.5 pb-28'}`}>
            <div className="mx-auto flex max-w-[1040px] flex-col gap-5">
              <Outlet />
            </div>
          </main>

          {!isDesktop && (
            <div className="pointer-events-none absolute inset-x-0 bottom-[22px] z-20 flex justify-center">
              <nav aria-label="Onglets" className="pointer-events-auto flex gap-1.5 rounded-full bg-night p-1.5 shadow-float">
                {TABS.map((t) => {
                  const on = activeTab === t.path
                  return (
                    <button
                      key={t.path}
                      type="button"
                      aria-label={t.label}
                      title={t.label}
                      aria-current={on ? 'page' : undefined}
                      onClick={() => navigate(t.path)}
                      className={`grid h-[52px] w-[52px] place-items-center rounded-full border-0 transition-colors ${on ? 'bg-white text-ink' : 'bg-transparent text-[#b9bcc2]'}`}
                    >
                      <Icon name={t.icon} size={22} />
                    </button>
                  )
                })}
              </nav>
            </div>
          )}

          {toastMsg && (
            <div
              role="status"
              aria-live="polite"
              className={`pointer-events-none absolute inset-x-0 z-40 flex justify-center px-4 ${isDesktop ? 'bottom-7' : 'bottom-[104px]'}`}
            >
              <span className="rounded-full bg-night px-[18px] py-3 text-sm font-semibold text-white shadow-float">{toastMsg.text}</span>
            </div>
          )}
        </div>
      </div>
    </ShellContext.Provider>
  )
}

function Sidebar({ pathname, activeTab, expiresAt }: { pathname: string; activeTab: string; expiresAt: number | null }) {
  const navigate = useNavigate()
  const left = useSecondsLeft(expiresAt)
  const isService = SERVICES.some((s) => pathname.startsWith(s.path))
  return (
    <aside className="flex w-[248px] flex-none flex-col gap-[22px] overflow-y-auto border-r border-[#e6e8eb] bg-white px-3.5 py-[22px]">
      <div className="px-2.5">
        <Brand />
      </div>
      <nav aria-label="Navigation principale" className="flex flex-col gap-0.5">
        {TABS.map((t) => {
          const on = activeTab === t.path && !isService
          return (
            <button
              key={t.path}
              type="button"
              aria-current={on ? 'page' : undefined}
              onClick={() => navigate(t.path)}
              className={`flex min-h-11 items-center gap-3 rounded-xl border-0 px-3 text-left text-[15px] font-semibold ${on ? 'bg-night text-white' : 'bg-transparent text-ink hover:bg-page'}`}
            >
              <Icon name={t.icon} />
              <span>{t.label}</span>
            </button>
          )
        })}
      </nav>
      <div className="flex flex-col gap-0.5">
        <span className="px-3 pb-1.5 text-xs font-semibold tracking-[0.04em] text-ink-3 uppercase">Services</span>
        {SERVICES.map((s) => {
          const on = pathname.startsWith(s.path)
          return (
            <button
              key={s.path}
              type="button"
              aria-current={on ? 'page' : undefined}
              onClick={() => navigate(s.path)}
              className={`flex min-h-11 items-center gap-3 rounded-xl border-0 px-3 text-left text-sm font-medium ${on ? 'bg-violet-bg text-violet-ink' : 'bg-transparent text-ink hover:bg-page'}`}
            >
              <Icon name={s.icon} />
              <span className="flex-1">{s.label}</span>
            </button>
          )
        })}
      </div>
      {left !== null && (
        <div className="mt-auto flex flex-col gap-2 rounded-[18px] bg-page p-3.5">
          <span className="text-xs font-medium text-ink-3">Session restante</span>
          <span className="tnum text-[22px] font-bold">{formatClock(left)}</span>
          <div className="h-1.5 overflow-hidden rounded-full bg-[#dfe1e5]">
            <div className="h-full rounded-full bg-night" style={{ width: sessionPct(left) }} />
          </div>
        </div>
      )}
    </aside>
  )
}

/** Cloche D13 : badge des non-lues (en erreur ou à zéro : pas de badge, rien ne casse). */
function Bell({ onOpen }: { onOpen: () => void }) {
  const { unreadCount } = useBankData()
  const count = unreadCount.data ?? 0
  const badge = badgeText(count)
  return (
    <button type="button" aria-label={bellLabel(count)} onClick={onOpen} className="round-btn relative flex-none">
      <Icon name="bell" />
      {badge && (
        <span aria-hidden data-testid="bell-badge" className="absolute -top-1 -right-1 grid h-5 min-w-5 place-items-center rounded-full bg-ko-fg px-1 text-[11px] font-bold text-white">
          {badge}
        </span>
      )}
    </button>
  )
}

/**
 * Bandeau D6 : visible pendant l'incident, « Service rétabli » à la reprise. La détection vient du
 * rafraîchissement 15 s des données (BankDataProvider) ; la reprise est sondée toutes les 5 s sur
 * GET /api/v1/status (public, en cache 2 s), puis confirmée par GET /api/v1/accounts avant
 * d'afficher « rétabli » (la BDD joignable ne prouve pas que les routes métier répondent).
 */
function ServiceBanner({ isDesktop }: { isDesktop: boolean }) {
  const status = useServiceStatus()
  const { accounts, transactions, beneficiaries, limits, unreadCount } = useBankData()
  const prev = useRef(status)

  useEffect(() => {
    if (status !== 'degraded') return
    // Sonde légère d'abord ; la reprise n'est déclarée que si une vraie route métier répond.
    const probe = async () => {
      if ((await api.getStatus()).status === 'ok') await api.getAccounts()
    }
    const id = setInterval(() => void probe().catch(() => {}), 5000)
    return () => clearInterval(id)
  }, [status])

  // À la reprise, on recharge les données pour effacer les états d'erreur sans action de l'utilisateur.
  useEffect(() => {
    if (prev.current === 'degraded' && status === 'restored') {
      accounts.reload()
      transactions.reload()
      beneficiaries.reload()
      limits.reload()
      unreadCount.reload()
    }
    prev.current = status
  }, [status, accounts, transactions, beneficiaries, limits, unreadCount])

  if (status === 'ok') return null
  const margin = isDesktop ? 'mx-10 mb-3' : 'mx-3 mb-2.5'
  const size = isDesktop ? 'text-xl' : 'text-[17px]'
  if (status === 'degraded') {
    return (
      <div role="status" aria-live="polite" className={`flex flex-none items-center gap-3.5 rounded-[18px] bg-night px-[18px] py-3.5 text-white shadow-[0_14px_28px_-16px_rgba(18,19,22,.6)] ${margin}`}>
        <span className="h-3 w-3 flex-none animate-pulse-warn rounded-full bg-[#f0b43c]" />
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className={`leading-tight font-semibold tracking-[-0.01em] ${size}`}>Service perturbé — reprise automatique en cours</span>
          <span className="text-[13px] text-ink-4">Vos opérations sont conservées et seront traitées automatiquement.</span>
        </span>
      </div>
    )
  }
  return (
    <div role="status" aria-live="polite" className={`flex flex-none items-center gap-3.5 rounded-[18px] bg-ok-bg px-[18px] py-3.5 text-[#14532d] ${margin}`}>
      <span className="grid h-7 w-7 flex-none place-items-center rounded-full bg-ok-fg text-white">
        <Icon name="check" size={16} />
      </span>
      <span className={`font-semibold tracking-[-0.01em] ${size}`}>Service rétabli</span>
    </div>
  )
}
