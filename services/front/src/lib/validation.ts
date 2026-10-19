export interface TransferInput {
  fromAccount: string
  toAccount: string
  amount: string
  balance: number | null
}

export type TransferErrors = Partial<Record<'fromAccount' | 'toAccount' | 'amount', string>>

/** Normalise une saisie de montant : « 1 200,5 » -> « 1200.5 ». */
function normalizeAmount(raw: string): string {
  return raw.trim().replace(/[\s\u00a0\u202f]/g, '').replace(',', '.')
}

/** Validation côté client (le serveur reste l'autorité). */
export function validateTransfer(input: TransferInput): TransferErrors {
  const errors: TransferErrors = {}
  if (!input.fromAccount) errors.fromAccount = 'Choisissez le compte à débiter.'

  // payment-api identifie les comptes par un id entier (TransactionIn.dst_account).
  const to = input.toAccount.trim()
  if (!to) errors.toAccount = 'Indiquez le compte bénéficiaire.'
  else if (!/^\d+$/.test(to) || Number(to) <= 0) errors.toAccount = "L'identifiant du compte doit être un entier positif."
  else if (to === input.fromAccount) errors.toAccount = 'Le bénéficiaire doit être différent du compte débité.'

  const raw = normalizeAmount(input.amount)
  if (!raw) errors.amount = 'Indiquez un montant.'
  else if (!/^\d+(\.\d*)?$/.test(raw)) errors.amount = 'Montant invalide. Exemple : 125,50'
  else if (!/^\d+(\.\d{0,2})?$/.test(raw)) errors.amount = 'Deux décimales maximum.'
  else if (Number(raw) <= 0) errors.amount = 'Le montant doit être supérieur à 0.'
  else if (input.balance !== null && Number(raw) > input.balance) errors.amount = 'Montant supérieur au solde disponible.'
  return errors
}

/** Montant saisi -> euros arrondis au centime ; null si la saisie n'est pas un nombre positif. */
export function parseAmount(raw: string): number | null {
  const s = normalizeAmount(raw)
  if (!/^\d+(\.\d*)?$/.test(s)) return null
  return Math.round(Number(s) * 100) / 100
}
