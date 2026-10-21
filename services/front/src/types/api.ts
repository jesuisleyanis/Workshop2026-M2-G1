// Types alignés sur docs/contracts.md (conventions d'API REST) et sur les routes /api/v1.
// Les corps de réponse métier (login, comptes, transactions) ne sont pas figés champ à champ
// par le contrat : voir CAHIER-DES-CHARGES.md du front, section "Hypothèses de schéma".

/** Corps d'erreur normalisé : { "error": { code, message, request_id } } */
export interface ApiErrorBody {
  error: { code: string; message: string; request_id?: string | null }
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  /** JWT HS256 (Bearer), durée 15 min. */
  accessToken: string
  tokenType: string
  /** Durée de vie en secondes, si fournie. */
  expiresIn: number | null
}

export interface Account {
  id: string
  owner: string | null
  label: string | null
  /** IBAN fictif (`iban_fake` côté payment-api), affiché tel quel. */
  iban: string | null
  balance: number
  currency: string
}

/** `result` des métriques resilience_transactions_total : created | rejected. */
export type TransactionStatus = 'created' | 'rejected'

/** Catégorie de dépense portée par la transaction (payment-api, #44). Défaut serveur : `transfer`. */
export type Category = 'food' | 'shopping' | 'transport' | 'subscriptions' | 'health' | 'leisure' | 'housing' | 'transfer' | 'other'

export interface Transaction {
  id: string
  fromAccount: string
  toAccount: string
  amount: number
  currency: string
  status: TransactionStatus
  /** Choisie par l'émetteur ; null pour un virement reçu (payment-api la masque). */
  category: Category | null
  label: string | null
  createdAt: string
  /** `request_id` de la requête de création (référence affichée au client, corrélée aux logs). */
  requestId: string | null
}

export interface TransferRequest {
  from_account: string
  to_account: string
  amount: number
  currency?: string
  label?: string
  /** Facultatif : absent, payment-api enregistre `transfer`. */
  category?: Category
}

/** GET /api/v1/stats/spending?period=week|month&offset=-n (#44) : dépenses d'une période (UTC), en euros. */
export interface Spending {
  period: 'week' | 'month'
  /** 0 = période en cours, -1 = précédente… */
  offset: number
  /** YYYY-MM-DD ; `end` exclusif. */
  start: string
  end: string
  total: number
  byCategory: { category: Category; amount: number; share: number }[]
  byDay: { date: string; amount: number }[]
}

/** GET /api/v1/status (payment-api, public) : 200 ok, 503 degraded. */
export interface ServiceHealth {
  status: 'ok' | 'degraded'
  checkedAt: string
}

/** Bénéficiaire enregistré (payment-api, #43). `accountId` = dst_account d'un virement. */
export interface Beneficiary {
  id: string
  name: string
  accountId: string
  iban: string
  createdAt: string | null
}

export interface NewBeneficiary {
  name: string
  iban: string
}
