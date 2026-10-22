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

/** GET /api/v1/limits (#46) : plafond mensuel de virement par compte, en euros. `limit` null = sans plafond. */
export interface AccountLimit {
  accountId: string
  limit: number | null
  used: number
  remaining: number | null
  /** YYYY-MM-DD, exclusif : date de remise à zéro (1er du mois suivant, UTC). */
  periodEnd: string
}

/** Carte bancaire fictive (payment-api, #47). Jamais de numéro complet ni de CVV. Montants en euros. */
export interface Card {
  id: string
  accountId: string
  last4: string
  holder: string
  expiryMonth: number
  expiryYear: number
  status: 'active' | 'frozen'
  paymentLimit: number
  contactless: boolean
  onlinePayments: boolean
}

export interface CardPatch {
  paymentLimit?: number
  contactless?: boolean
  onlinePayments?: boolean
}

/** Virement programmé (#48, D12) : exécuté par payment-api, mêmes règles que les virements. */
export type ScheduleFrequency = 'once' | 'weekly' | 'monthly'
export type ScheduleStatus = 'active' | 'paused' | 'cancelled' | 'completed'

export interface ScheduledTransfer {
  id: string
  fromAccount: string
  toAccount: string
  /** En euros. */
  amount: number
  category: Category
  frequency: ScheduleFrequency
  /** YYYY-MM-DD. */
  startOn: string
  nextRunOn: string | null
  endOn: string | null
  status: ScheduleStatus
  lastRun: { runOn: string; status: 'pending' | 'executed' | 'failed'; errorCode: string | null } | null
}

export interface NewSchedule {
  fromAccount: string
  toAccount: string
  /** En euros. */
  amount: number
  category?: Category
  frequency: ScheduleFrequency
  startOn: string
  endOn?: string | null
}

/** Notification in-app (#49, D13). Titre et corps rédigés côté serveur : affichés en texte brut. */
export type NotificationType =
  | 'transfer_sent'
  | 'transfer_received'
  | 'transfer_rejected'
  | 'limit_80'
  | 'card_frozen'
  | 'card_unfrozen'
  | 'scheduled_executed'
  | 'scheduled_failed'
  /** Type inconnu d'un serveur plus récent : affiché avec une icône neutre. */
  | 'other'

export interface AppNotification {
  id: string
  type: NotificationType
  title: string
  body: string
  createdAt: string
  readAt: string | null
}

/** Paramètres d'un relevé (#50) : bornes incluses, jours UTC (YYYY-MM-DD). */
export interface StatementQuery {
  accountId: string
  from: string
  to: string
}

/** GET /api/v1/statements?format=json (#50), montants en euros. */
export interface Statement {
  accountId: string
  iban: string
  holder: string
  from: string
  to: string
  rows: {
    id: string
    createdAt: string
    reference: string
    direction: 'debit' | 'credit'
    counterpartyAccount: string
    category: Category | null
    amount: number
    status: TransactionStatus
  }[]
  totalDebit: number
  totalCredit: number
}
