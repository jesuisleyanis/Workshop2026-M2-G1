import { ApiError } from './errors'
import type { Account, Beneficiary, LoginResponse, ServiceHealth, Transaction, TransactionStatus } from '../types/api'

type Obj = Record<string, unknown>

function asObj(v: unknown, what: string): Obj {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) {
    throw new ApiError(0, 'invalid_response', `Réponse invalide (${what}).`)
  }
  return v as Obj
}

function toStr(v: unknown, key: string, what: string): string {
  if (typeof v === 'string' && v !== '') return v
  if (typeof v === 'number') return String(v)
  throw new ApiError(0, 'invalid_response', `Champ « ${key} » manquant (${what}).`)
}

function str(o: Obj, key: string, what: string): string {
  return toStr(o[key], key, what)
}

function optStr(o: Obj, key: string): string | null {
  const v = o[key]
  return typeof v === 'string' && v !== '' ? v : null
}

/** Les décimaux Python/Postgres peuvent arriver sous forme de chaîne ("1250.50"). */
function num(o: Obj, key: string, what: string): number {
  const v = o[key]
  const n = typeof v === 'string' ? Number(v) : v
  if (typeof n === 'number' && Number.isFinite(n)) return n
  throw new ApiError(0, 'invalid_response', `Champ « ${key} » invalide (${what}).`)
}

function list(v: unknown, wrapperKey: string, what: string): unknown[] {
  if (Array.isArray(v)) return v
  const o = asObj(v, what)
  const inner = o[wrapperKey] ?? o.items
  if (Array.isArray(inner)) return inner
  throw new ApiError(0, 'invalid_response', `Liste attendue (${what}).`)
}

export function parseLogin(v: unknown): LoginResponse {
  const o = asObj(v, 'login')
  const token = o.access_token ?? o.token
  if (typeof token !== 'string' || token === '') {
    throw new ApiError(0, 'invalid_response', 'Jeton absent de la réponse de connexion.')
  }
  const exp = o.expires_in
  return {
    accessToken: token,
    tokenType: typeof o.token_type === 'string' ? o.token_type : 'bearer',
    expiresIn: typeof exp === 'number' ? exp : null,
  }
}

export function parseAccount(v: unknown): Account {
  const o = asObj(v, 'compte')
  // Contrat payment-api (AccountOut) : { id, iban_fake, balance_cents, currency }.
  // Les montants transitent en centimes entiers ; l'UI raisonne en euros.
  const balance = 'balance_cents' in o ? num(o, 'balance_cents', 'compte') / 100 : num(o, 'balance', 'compte')
  return {
    id: str(o, 'id', 'compte'),
    owner: optStr(o, 'owner'),
    label: optStr(o, 'label') ?? optStr(o, 'name') ?? optStr(o, 'iban_fake'),
    iban: optStr(o, 'iban_fake') ?? optStr(o, 'iban'),
    balance,
    currency: optStr(o, 'currency') ?? 'EUR',
  }
}

export function parseAccounts(v: unknown): Account[] {
  return list(v, 'accounts', 'comptes').map(parseAccount)
}

function parseStatus(v: unknown): TransactionStatus {
  return v === 'rejected' ? 'rejected' : 'created'
}

export function parseTransaction(v: unknown): Transaction {
  const o = asObj(v, 'transaction')
  // Contrat payment-api (TransactionOut) : { id, src_account, dst_account, amount_cents, status }.
  // src_/dst_account et amount_cents (centimes) ; pas d'horodatage côté API pour l'instant.
  const amount = 'amount_cents' in o ? num(o, 'amount_cents', 'transaction') / 100 : num(o, 'amount', 'transaction')
  return {
    id: str(o, 'id', 'transaction'),
    fromAccount: toStr(o.src_account ?? o.from_account, 'src_account', 'transaction'),
    toAccount: toStr(o.dst_account ?? o.to_account, 'dst_account', 'transaction'),
    amount,
    currency: optStr(o, 'currency') ?? 'EUR',
    status: parseStatus(o.status),
    label: optStr(o, 'label'),
    createdAt: optStr(o, 'created_at') ?? '',
    requestId: optStr(o, 'request_id'),
  }
}

export function parseTransactions(v: unknown): Transaction[] {
  return list(v, 'transactions', 'transactions').map(parseTransaction)
}

export function parseServiceHealth(v: unknown): ServiceHealth {
  const o = asObj(v, 'état du service')
  return { status: o.status === 'ok' ? 'ok' : 'degraded', checkedAt: str(o, 'checked_at', 'état du service') }
}

export function parseBeneficiary(v: unknown): Beneficiary {
  const o = asObj(v, 'bénéficiaire')
  return {
    id: str(o, 'id', 'bénéficiaire'),
    name: str(o, 'display_name', 'bénéficiaire'),
    accountId: str(o, 'account_id', 'bénéficiaire'),
    iban: str(o, 'iban_fake', 'bénéficiaire'),
    createdAt: optStr(o, 'created_at'),
  }
}

export function parseBeneficiaries(v: unknown): Beneficiary[] {
  return list(v, 'beneficiaries', 'bénéficiaires').map(parseBeneficiary)
}
