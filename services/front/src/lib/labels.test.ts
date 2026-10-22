import { describe, expect, it } from 'vitest'
import { tokenStore } from '../api/tokenStore'
import { labelStore } from './labels'

const jwtFor = (sub: string) => {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, '')
  return `${b64({ alg: 'HS256' })}.${b64({ sub, exp: Math.floor(Date.now() / 1000) + 600 })}.sig`
}

describe('labelStore', () => {
  it('persiste les libellés par id de transaction', () => {
    tokenStore.set(jwtFor('demo01'))
    expect(labelStore.all()).toEqual({})
    labelStore.save('42', 'Loyer')
    expect(labelStore.all()).toEqual({ '42': 'Loyer' })
  })

  it('cloisonne par utilisateur : un poste partagé ne révèle pas les libellés d’autrui', () => {
    tokenStore.set(jwtFor('demo01'))
    labelStore.save('42', 'Cadeau secret')
    tokenStore.set(jwtFor('demo03'))
    expect(labelStore.all()).toEqual({})
    tokenStore.clear()
    expect(labelStore.all()).toEqual({}) // sans session : rien
  })

  it('ignore un contenu corrompu et supprime l’ancienne clé commune', () => {
    tokenStore.set(jwtFor('demo01'))
    localStorage.setItem('resilience.labels', '{"42":"ancien"}')
    localStorage.setItem('resilience.labels.demo01', '{oops')
    expect(labelStore.all()).toEqual({})
    expect(localStorage.getItem('resilience.labels')).toBeNull()
  })
})
