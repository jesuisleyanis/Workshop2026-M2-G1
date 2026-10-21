import { API_BASE } from '../config'
import { createApiClient, type ApiClient } from './client'
import { parseAccounts, parseLogin, parseTransaction, parseTransactions } from './parsers'
import { tokenStore } from './tokenStore'
import { serviceStatus } from '../lib/serviceStatus'
import type { Account, LoginRequest, LoginResponse, Transaction, TransferRequest } from '../types/api'

/** Endpoints métier /api/v1 (docs/contracts.md : préfixe /api/v1, JWT Bearer). */
export function createEndpoints(client: ApiClient) {
  return {
    login: async (creds: LoginRequest): Promise<LoginResponse> =>
      parseLogin(await client.request('/api/v1/login', { method: 'POST', body: creds, auth: false })),
    getAccounts: async (signal?: AbortSignal): Promise<Account[]> =>
      parseAccounts(await client.request('/api/v1/accounts', { signal })),
    listTransactions: async (signal?: AbortSignal): Promise<Transaction[]> =>
      parseTransactions(await client.request('/api/v1/transactions', { signal })),
    createTransaction: async (req: TransferRequest): Promise<Transaction> =>
      // L'UI raisonne en euros / IBAN affiché ; payment-api attend des ids de compte
      // entiers et un montant en centimes (TransactionIn : src_account, dst_account, amount_cents).
      parseTransaction(
        await client.request('/api/v1/transactions', {
          method: 'POST',
          body: {
            src_account: Number(req.from_account),
            dst_account: Number(req.to_account),
            amount_cents: Math.round(req.amount * 100),
          },
        }),
      ),
  }
}

export type Endpoints = ReturnType<typeof createEndpoints>

let unauthorizedHandler: (() => void) | null = null

/** Le AuthProvider enregistre ici la déconnexion déclenchée par un 401. */
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  unauthorizedHandler = fn
}

export const client = createApiClient({
  baseUrl: API_BASE,
  getToken: () => tokenStore.get(),
  onUnauthorized: () => unauthorizedHandler?.(),
  onAvailability: (up, startedAt) => serviceStatus.report(up, startedAt),
})

export const api = createEndpoints(client)
