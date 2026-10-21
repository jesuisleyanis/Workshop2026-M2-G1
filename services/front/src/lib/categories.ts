import type { IconName } from '../components/icons'
import type { Category } from '../types/api'

export interface CategoryInfo {
  id: Category
  label: string
  icon: IconName
  /** Teinte de gris (maquette D8 noir & blanc) : fond de pastille / barre. */
  tone: string
}

/** Les 9 catégories de payment-api (#44), dans l'ordre d'affichage du sélecteur. */
export const CATEGORIES: readonly CategoryInfo[] = [
  { id: 'transfer', label: 'Virement', icon: 'swap', tone: '#121316' },
  { id: 'food', label: 'Alimentation', icon: 'food', tone: '#2a2c32' },
  { id: 'shopping', label: 'Shopping', icon: 'bag', tone: '#3f4249' },
  { id: 'transport', label: 'Transport', icon: 'car', tone: '#555962' },
  { id: 'subscriptions', label: 'Abonnements', icon: 'repeat', tone: '#6b6f76' },
  { id: 'health', label: 'Santé', icon: 'heart', tone: '#82868d' },
  { id: 'leisure', label: 'Loisirs', icon: 'star', tone: '#9a9ea6' },
  { id: 'housing', label: 'Logement', icon: 'home', tone: '#b1b4ba' },
  { id: 'other', label: 'Autre', icon: 'grid', tone: '#c8cbd0' },
]

const BY_ID = new Map(CATEGORIES.map((c) => [c.id, c]))

export const isCategory = (v: unknown): v is Category => typeof v === 'string' && BY_ID.has(v as Category)
export const categoryInfo = (c: Category): CategoryInfo => BY_ID.get(c) ?? BY_ID.get('other')!
export const categoryLabel = (c: Category): string => categoryInfo(c).label
export const formatShare = (share: number): string => `${Math.round(share * 100)} %`
