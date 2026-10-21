import { API_BASE } from '../config'
import { createApiClient, type ApiClient } from './client'
import { parseAccounts, parseBeneficiaries, parseBeneficiary, parseCard, parseCards, parseLimits, parseLogin, parseServiceHealth, parseSpending, parseTransaction, parseTransactions } from './parsers'
import { tokenStore } from './tokenStore'
import { serviceStatus } from '../lib/serviceStatus'
import type { Account, AccountLimit, Beneficiary, Card, CardPatch, LoginRequest, LoginResponse, NewBeneficiary, ServiceHealth, Spending, Transaction, TransferRequest } from '../types/api'

/** Endpoints métier /api/v1 (docs/contracts.md : préfixe /api/v1, JWT Bearer). */
export function createEndpoints(client: ApiClient) {
  return {
    login: async (creds: LoginRequest): Promise<LoginResponse> =>
      parseLogin(await client.request('/api/v1/login', { method: 'POST', body: creds, auth: false })),
    // Public et mis en cache côté serveur. Un 503 « degraded » signale la panne ; un 200 ne prouve
    // que l'accès BDD de payment-api, pas la reprise des routes métier (reportRecovery: false).
    getStatus: async (signal?: AbortSignal): Promise<ServiceHealth> =>
      parseServiceHealth(await client.request('/api/v1/status', { auth: false, signal, reportRecovery: false })),
    getAccounts: async (signal?: AbortSignal): Promise<Account[]> =>
      parseAccounts(await client.request('/api/v1/accounts', { signal })),
    listBeneficiaries: async (signal?: AbortSignal): Promise<Beneficiary[]> =>
      parseBeneficiaries(await client.request('/api/v1/beneficiaries', { signal })),
    addBeneficiary: async (b: NewBeneficiary): Promise<Beneficiary> =>
      parseBeneficiary(
        await client.request('/api/v1/beneficiaries', { method: 'POST', body: { display_name: b.name, iban_fake: b.iban } }),
      ),
    deleteBeneficiary: async (id: string): Promise<void> => {
      await client.request(`/api/v1/beneficiaries/${encodeURIComponent(id)}`, { method: 'DELETE' })
    },
    getTransaction: async (id: string, signal?: AbortSignal): Promise<Transaction> =>
      parseTransaction(await client.request(`/api/v1/transactions/${encodeURIComponent(id)}`, { signal })),
    getLimits: async (signal?: AbortSignal): Promise<AccountLimit[]> =>
      parseLimits(await client.request('/api/v1/limits', { signal })),
    listCards: async (signal?: AbortSignal): Promise<Card[]> => parseCards(await client.request('/api/v1/cards', { signal })),
    freezeCard: async (id: string): Promise<Card> =>
      parseCard(await client.request(`/api/v1/cards/${encodeURIComponent(id)}/freeze`, { method: 'POST' })),
    unfreezeCard: async (id: string): Promise<Card> =>
      parseCard(await client.request(`/api/v1/cards/${encodeURIComponent(id)}/unfreeze`, { method: 'POST' })),
    // Corps partiel : seuls les champs fournis sont envoyés ; plafond converti en centimes entiers.
    updateCard: async (id: string, patch: CardPatch): Promise<Card> =>
      parseCard(
        await client.request(`/api/v1/cards/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          body: {
            ...(patch.paymentLimit !== undefined ? { payment_limit_cents: Math.round(patch.paymentLimit * 100) } : {}),
            ...(patch.contactless !== undefined ? { contactless: patch.contactless } : {}),
            ...(patch.onlinePayments !== undefined ? { online_payments: patch.onlinePayments } : {}),
          },
        }),
      ),
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
            ...(req.category ? { category: req.category } : {}),
          },
        }),
      ),
    getSpending: async (period: 'week' | 'month', offset = 0, signal?: AbortSignal): Promise<Spending> =>
      parseSpending(await client.request(`/api/v1/stats/spending?period=${period}&offset=${Math.min(0, Math.trunc(offset))}`, { signal })),
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
