import { useEffect, useState } from 'react'
import { deviceStatus } from '../api/auth'

/** Rafraîchissement du statut du module (dernier statut MQTT connu par `auth`). */
export const DEVICE_POLL_MS = 15_000

type Status = 'online' | 'offline' | 'unknown'

const VIEW: Record<Status, { text: string; dot: string }> = {
  online: { text: 'Module LED en ligne', dot: 'var(--color-led-green)' },
  offline: { text: 'Module LED hors ligne', dot: 'var(--color-led-red)' },
  unknown: { text: 'Module LED inconnu', dot: '#8a8f97' },
}

// Pastille d'état du module LED (ESP8266) sur le panneau nuit. `null` côté API = LED simulée
// ou aucun statut reçu : « inconnu ». Toute erreur réseau retombe aussi sur « inconnu ».
export function DevicePill() {
  const [status, setStatus] = useState<Status | null>(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      deviceStatus().then(
        (r) => alive && setStatus(r.led_online === true ? 'online' : r.led_online === false ? 'offline' : 'unknown'),
        () => alive && setStatus('unknown'),
      )
    void load()
    const id = setInterval(load, DEVICE_POLL_MS)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  const view = VIEW[status ?? 'unknown']
  return (
    <span
      role="status"
      className="inline-flex w-fit items-center gap-2 rounded-full border border-[#33363d] bg-night-2 px-3 py-1.5 text-[13px] text-[#a7abb3]"
    >
      <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: view.dot }} />
      {status === null ? 'Module LED…' : view.text}
    </span>
  )
}
