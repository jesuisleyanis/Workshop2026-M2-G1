import { describe, expect, it } from 'vitest'
import { labelStore } from './labels'

describe('labelStore', () => {
  it('persiste les libellés par id de transaction', () => {
    expect(labelStore.all()).toEqual({})
    labelStore.save('42', 'Loyer')
    expect(labelStore.all()).toEqual({ '42': 'Loyer' })
  })
  it('ignore un contenu corrompu', () => {
    localStorage.setItem('resilience.labels', '{oops')
    expect(labelStore.all()).toEqual({})
  })
})
