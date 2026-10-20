// Miroir côté UI de l'état de la LED physique (contrat §5.3). La vraie LED est pilotée par
// `auth` via MQTT ; le back-office en affiche un reflet pour l'opérateur.

export type LedState = 'idle' | 'recognized' | 'auth_ok' | 'auth_fail' | 'not_recognized'

export interface LedView {
  color: 'off' | 'green' | 'red'
  blink: boolean
  label: string
}

const VIEWS: Record<LedState, LedView> = {
  idle: { color: 'off', blink: false, label: 'En attente' },
  recognized: { color: 'green', blink: true, label: 'Visage reconnu — saisissez le mot de passe' },
  auth_ok: { color: 'green', blink: false, label: 'Accès autorisé' },
  auth_fail: { color: 'red', blink: true, label: 'Mot de passe incorrect' },
  not_recognized: { color: 'red', blink: false, label: 'Visage non reconnu' },
}

export function ledView(state: LedState): LedView {
  return VIEWS[state]
}
