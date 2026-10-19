export interface TransferInput {
  fromAccount: string
  toAccount: string
  amount: string
  balance: number | null
}

export type TransferErrors = Partial<Record<'fromAccount' | 'toAccount' | 'amount', string>>

/** Validation côté client (le serveur reste l'autorité). */
export function validateTransfer(input: TransferInput): TransferErrors {
  const errors: TransferErrors = {}
  if (!input.fromAccount) errors.fromAccount = 'Choisissez le compte à débiter.'
  const to = input.toAccount.trim()
  if (!to) errors.toAccount = 'Indiquez le compte bénéficiaire.'
  else if (to === input.fromAccount) errors.toAccount = 'Le bénéficiaire doit être différent du compte débité.'

  const raw = input.amount.trim().replace(',', '.')
  const amount = Number(raw)
  if (!/^\d+(\.\d+)?$/.test(raw) || !Number.isFinite(amount) || amount <= 0) {
    errors.amount = 'Montant invalide (supérieur à 0).'
  } else if (!/^\d+(\.\d{1,2})?$/.test(raw)) {
    errors.amount = 'Maximum 2 décimales.'
  } else if (input.balance !== null && amount > input.balance) {
    errors.amount = 'Montant supérieur au solde disponible.'
  }
  return errors
}

export function parseAmount(raw: string): number {
  return Math.round(Number(raw.replace(',', '.')) * 100) / 100
}
