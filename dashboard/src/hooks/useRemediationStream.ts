import { useEffect, useRef } from 'react'
import { parseStreamMessage } from '../lib/parse'
import { SSE_EVENT_NAMES, type ConnectionStatus, type StreamMessage } from '../types/events'

/** Sous-ensemble d'EventSource utilisé (permet l'injection dans les tests). */
export interface EventSourceLike {
  readyState: number
  onopen: ((ev: Event) => void) | null
  onerror: ((ev: Event) => void) | null
  addEventListener(type: string, listener: (ev: MessageEvent) => void): void
  close(): void
}
export type EventSourceFactory = (url: string) => EventSourceLike

export const defaultFactory: EventSourceFactory = (url) => new EventSource(url) as unknown as EventSourceLike

interface Handlers {
  onMessage: (m: StreamMessage) => void
  onRejected: () => void
  onStatus: (s: ConnectionStatus) => void
}

const CLOSED = 2

/**
 * Ouvre le flux SSE du moteur de remédiation. EventSource se reconnecte seul : on reflète
 * l'état (connecting / open / reconnecting / closed) et on valide chaque message.
 */
export function useRemediationStream(url: string, handlers: Handlers, factory: EventSourceFactory = defaultFactory): void {
  const ref = useRef(handlers)
  useEffect(() => {
    ref.current = handlers
  })

  useEffect(() => {
    ref.current.onStatus('connecting')
    const es = factory(url)

    const handle = (name: string) => (ev: MessageEvent) => {
      const parsed = parseStreamMessage(name, typeof ev.data === 'string' ? ev.data : '')
      if (parsed.ok) ref.current.onMessage(parsed.value)
      else ref.current.onRejected()
    }
    for (const name of SSE_EVENT_NAMES) es.addEventListener(name, handle(name))
    es.addEventListener('message', handle('message'))

    es.onopen = () => ref.current.onStatus('open')
    es.onerror = () => ref.current.onStatus(es.readyState === CLOSED ? 'closed' : 'reconnecting')

    return () => es.close()
  }, [url, factory])
}
