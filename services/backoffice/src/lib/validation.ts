// Règles de saisie des comptes, miroir de celles du serveur (`auth`) : le serveur reste
// l'autorité, ces contrôles évitent seulement un aller-retour (et une capture inutile).
import type { AgentRole } from '../api/admin'

export const USERNAME_RE = /^[A-Za-z0-9_.-]{3,32}$/
export const PASSWORD_MIN_BYTES = 8
export const PASSWORD_MAX_BYTES = 72 // limite bcrypt, en octets UTF-8

export const ROLES: readonly AgentRole[] = ['customer', 'operator', 'admin']
export const ROLE_LABELS: Record<AgentRole, string> = {
  customer: 'Client',
  operator: 'Opérateur',
  admin: 'Administrateur',
}

const passwordBytes = (p: string) => new TextEncoder().encode(p).length

export function validateUsername(username: string): string | null {
  return USERNAME_RE.test(username)
    ? null
    : 'Identifiant invalide : 3 à 32 caractères parmi lettres, chiffres, « _ », « . » et « - ».'
}

export function validatePassword(password: string): string | null {
  const n = passwordBytes(password)
  if (n < PASSWORD_MIN_BYTES) return 'Mot de passe trop court : 8 octets minimum.'
  if (n > PASSWORD_MAX_BYTES) return 'Mot de passe trop long : 72 octets maximum.'
  return null
}

export interface CredentialErrors {
  username?: string
  password?: string
  confirm?: string
}

export function validateCredentials(v: { username: string; password: string; confirm: string }): CredentialErrors {
  const errors: CredentialErrors = {}
  const u = validateUsername(v.username)
  if (u) errors.username = u
  const p = validatePassword(v.password)
  if (p) errors.password = p
  else if (v.password !== v.confirm) errors.confirm = 'Les mots de passe ne correspondent pas.'
  return errors
}
