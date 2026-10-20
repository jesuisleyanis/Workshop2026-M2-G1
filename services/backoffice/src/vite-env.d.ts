/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base d'URL de l'API (vide = same-origin derrière le WAF). */
  readonly VITE_API_BASE?: string
}
