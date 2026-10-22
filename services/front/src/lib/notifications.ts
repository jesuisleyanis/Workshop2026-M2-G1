import type { IconName } from '../components/icons'
import type { AppNotification, NotificationType } from '../types/api'
import { dayKey, dayLabel } from './bank'

/** Polling du badge de la cloche (onglet visible seulement). */
export const NOTIFICATIONS_POLL_MS = 30_000

const ICONS: Record<NotificationType, IconName> = {
  transfer_sent: 'outArrow',
  transfer_received: 'inArrow',
  transfer_rejected: 'x',
  limit_80: 'alert',
  card_frozen: 'card',
  card_unfrozen: 'card',
  scheduled_executed: 'clock',
  scheduled_failed: 'alert',
  other: 'bell',
}

export const notificationIcon = (t: NotificationType): IconName => ICONS[t]

/** « 9+ » au-delà de 9 ; null si rien à signaler (pas de badge). */
export function badgeText(count: number): string | null {
  if (count <= 0) return null
  return count > 9 ? '9+' : String(count)
}

export const bellLabel = (count: number) =>
  count > 0 ? `Notifications, ${count} non lue${count > 1 ? 's' : ''}` : 'Notifications'

export interface NotificationGroup {
  key: string
  label: string
  items: AppNotification[]
}

/** Groupes par jour (même libellés que l'historique : « Aujourd'hui », « Hier », « Lundi 19 octobre »). */
export function groupNotifications(items: AppNotification[], now = new Date()): NotificationGroup[] {
  const groups: NotificationGroup[] = []
  for (const n of items) {
    const key = dayKey(n.createdAt)
    let g = groups.find((x) => x.key === key)
    if (!g) {
      g = { key, label: dayLabel(key, now), items: [] }
      groups.push(g)
    }
    g.items.push(n)
  }
  return groups
}
