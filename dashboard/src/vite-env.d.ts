/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base du moteur de remédiation (flux SSE = <base>/stream). */
  readonly VITE_REMEDIATION_BASE?: string
  /** Base de Grafana pour les liens. */
  readonly VITE_GRAFANA_BASE?: string
  /** Source des événements : live (défaut) | auto | simulation. */
  readonly VITE_STREAM_SOURCE?: string
  /** "true" : boutons de déclenchement aussi en flux réel hors dev (mock uniquement). */
  readonly VITE_LIVE_TRIGGERS?: string
}
