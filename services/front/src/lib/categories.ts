import type { IconName } from '../components/icons'
import type { Category } from '../types/api'

export interface CategoryInfo {
  id: Category
  label: string
  icon: IconName
  /** Couleur propre à la catégorie (fond de pastille / barre) ; assez foncée pour l'icône blanche. */
  tone: string
}

/** Les 9 catégories de payment-api (#44), dans l'ordre d'affichage du sélecteur. */
export const CATEGORIES: readonly CategoryInfo[] = [
  { id: 'transfer', label: 'Virement', icon: 'swap', tone: '#6d4aff' },
  { id: 'food', label: 'Alimentation', icon: 'food', tone: '#ea580c' },
  { id: 'shopping', label: 'Shopping', icon: 'bag', tone: '#db2777' },
  { id: 'transport', label: 'Transport', icon: 'car', tone: '#2563eb' },
  { id: 'subscriptions', label: 'Abonnements', icon: 'repeat', tone: '#0891b2' },
  { id: 'health', label: 'Santé', icon: 'heart', tone: '#dc2626' },
  { id: 'leisure', label: 'Loisirs', icon: 'star', tone: '#16a34a' },
  { id: 'housing', label: 'Logement', icon: 'home', tone: '#92400e' },
  { id: 'other', label: 'Autre', icon: 'grid', tone: '#64748b' },
]

const BY_ID = new Map(CATEGORIES.map((c) => [c.id, c]))

export const isCategory = (v: unknown): v is Category => typeof v === 'string' && BY_ID.has(v as Category)
export const categoryInfo = (c: Category): CategoryInfo => BY_ID.get(c) ?? BY_ID.get('other')!
export const categoryLabel = (c: Category): string => categoryInfo(c).label
export const formatShare = (share: number): string => `${Math.round(share * 100)} %`
