import { ApiError } from './errors'
import type { Account, LoginResponse, Transaction, TransactionStatus } from '../types/api'

type Obj = Record<string, unknown>

function asObj(v: unknown, what: string): Obj {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) {
    throw new ApiError(0, 'invalid_response', `Réponse invalide (${what}).`)
  }
  return v as Obj
}

function str(o: Obj, key: string, what: string): string {
  const v = o[key]
  if (typeof v === 'string' && v !== '') return v
  if (typeof v === 'number') return String(v)
  throw new ApiError(0, 'invalid_response', `Champ « ${key} » manquant (${what}).`)
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
  return {
    id: str(o, 'id', 'compte'),
    owner: optStr(o, 'owner'),
    label: optStr(o, 'label') ?? optStr(o, 'name'),
    balance: num(o, 'balance', 'compte'),
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
  return {
    id: str(o, 'id', 'transaction'),
    fromAccount: str(o, 'from_account', 'transaction'),
    toAccount: str(o, 'to_account', 'transaction'),
    amount: num(o, 'amount', 'transaction'),
    currency: optStr(o, 'currency') ?? 'EUR',
    status: parseStatus(o.status),
    label: optStr(o, 'label'),
    createdAt: str(o, 'created_at', 'transaction'),
  }
}

export function parseTransactions(v: unknown): Transaction[] {
  return list(v, 'transactions', 'transactions').map(parseTransaction)
}
