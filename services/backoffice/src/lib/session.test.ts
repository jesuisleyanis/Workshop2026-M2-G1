import { beforeEach, describe, expect, it } from 'vitest'
import { clearSession, decodeRole, getSession, setSession } from './session'

function jwt(payload: object): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${b64({ alg: 'HS256' })}.${b64(payload)}.sig`
}

beforeEach(() => clearSession())

describe('session en mémoire', () => {
  it('stocke le jeton uniquement en mémoire (aucun storage)', () => {
    expect(getSession()).toBeNull()
    setSession({ access_token: 'T', token_type: 'bearer', expires_in: 60, role: 'admin' })
    expect(getSession()?.access_token).toBe('T')
    expect(sessionStorage.length).toBe(0)
    expect(localStorage.length).toBe(0)
    clearSession()
    expect(getSession()).toBeNull()
  })

  it('decodeRole lit la claim role du JWT', () => {
    expect(decodeRole(jwt({ sub: 'a', role: 'operator' }))).toBe('operator')
  })

  it('decodeRole renvoie null si jeton illisible ou sans role', () => {
    expect(decodeRole('pas-un-jwt')).toBeNull()
    expect(decodeRole(jwt({ sub: 'a' }))).toBeNull()
    expect(decodeRole('a.%%%.c')).toBeNull()
  })
})
