import { useContext } from 'react'
import { BankDataContext, type BankData } from './bank-data-context'

export function useBankData(): BankData {
  const ctx = useContext(BankDataContext)
  if (!ctx) throw new Error('useBankData doit être utilisé dans <BankDataProvider>')
  return ctx
}
