import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/icons'
import { EmptyState, ErrorState, LoadingState } from '../components/ui'
import { useBankData } from '../hooks/useBankData'
import { useNotifications } from '../hooks/useNotifications'
import { useShell } from '../hooks/shell-context'
import { userMessage } from '../lib/errorMessages'
import { formatTime } from '../lib/format'
import { groupNotifications, notificationIcon } from '../lib/notifications'
import type { AppNotification } from '../types/api'

/** D13 — Notifications : groupées par jour, lue / non lue, clic = lue, « Tout marquer comme lu ». */
export function NotificationsPage() {
  const all = useNotifications(false)
  const { unreadCount } = useBankData()
  // Le sondage du badge (30 s) rafraîchit la liste quand de NOUVELLES notifications arrivent (compteur en
  // hausse) : ni au montage (chargement déjà en cours), ni après un marquage lu (compteur en baisse).
  const { reload: reloadAll } = all
  const prevCount = useRef<number | null>(null)
  useEffect(() => {
    const prev = prevCount.current
    prevCount.current = unreadCount.data
    if (prev !== null && unreadCount.data !== null && unreadCount.data > prev) reloadAll()
  }, [unreadCount.data, reloadAll])
  const { toast } = useShell()
  // Réponses serveur après un marquage, valables pour CE chargement : un rechargement l'emporte.
  const [read, setRead] = useState<{ data: AppNotification[] | null; map: Record<string, AppNotification> }>({ data: null, map: {} })
  const [busy, setBusy] = useState(false)

  if (all.error && !all.data) return <ErrorState error={all.error} onRetry={all.reload} />
  if (!all.data) return <LoadingState label="Chargement des notifications…" />
  if (all.data.length === 0) return <EmptyState title="Aucune notification" text="Vos virements, plafonds et cartes apparaîtront ici." icon="bell" />

  const overrides = read.data === all.data ? read.map : {}
  const items = all.data.map((n) => overrides[n.id] ?? n)
  const unread = items.filter((n) => !n.readAt).length
  const keep = (n: AppNotification) =>
    setRead((r) => ({ data: all.data, map: { ...(r.data === all.data ? r.map : {}), [n.id]: n } }))

  const open = async (n: AppNotification) => {
    if (n.readAt) return
    try {
      keep(await api.markNotificationRead(n.id))
      unreadCount.reload()
    } catch (e) {
      toast(userMessage(e))
    }
  }
  const readAll = async () => {
    setBusy(true)
    try {
      await api.markAllNotificationsRead()
      all.reload()
      unreadCount.reload()
    } catch (e) {
      toast(userMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[620px] flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-ink-3">{unread > 0 ? `${unread} non lue${unread > 1 ? 's' : ''}` : 'Tout est lu'}</span>
        <button type="button" onClick={() => void readAll()} disabled={busy || unread === 0} className="btn-ghost h-11 text-sm">
          <Icon name="check" size={16} />
          Tout marquer comme lu
        </button>
      </div>
      {groupNotifications(items).map((g) => (
        <section key={g.key || 'none'} aria-label={g.label} className="flex flex-col gap-2">
          <h2 className="m-0 px-1 text-sm font-semibold text-ink-3">{g.label}</h2>
          <ul className="m-0 flex list-none flex-col rounded-3xl bg-white p-1.5 shadow-card">
            {g.items.map((n) => {
              const isUnread = !n.readAt
              return (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => void open(n)}
                    aria-label={`${isUnread ? 'Non lue : ' : ''}${n.title}`}
                    className="flex min-h-[64px] w-full items-start gap-3 rounded-2xl border-0 bg-transparent px-2.5 py-2.5 text-left hover:bg-page"
                  >
                    <span className="grid h-10 w-10 flex-none place-items-center rounded-xl bg-page text-ink-2">
                      <Icon name={notificationIcon(n.type)} size={18} />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className={`text-[15px] ${isUnread ? 'font-bold' : 'font-medium text-ink-2'}`}>{n.title}</span>
                      <span className="text-[13px] text-ink-3">{n.body}</span>
                    </span>
                    <span className="flex flex-none flex-col items-end gap-1.5">
                      <span className="tnum text-xs text-ink-3">{formatTime(n.createdAt)}</span>
                      {isUnread && <span data-testid="unread-dot" className="h-2.5 w-2.5 rounded-full bg-ko-fg" />}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}
