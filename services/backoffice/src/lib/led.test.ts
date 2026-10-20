import { describe, expect, it } from 'vitest'
import { ledView } from './led'

describe('ledView (contrat §5.3)', () => {
  it('éteinte au repos', () => {
    expect(ledView('idle')).toMatchObject({ color: 'off', blink: false })
  })
  it('vert clignotant quand reconnu', () => {
    expect(ledView('recognized')).toMatchObject({ color: 'green', blink: true })
  })
  it('vert fixe à la réussite', () => {
    expect(ledView('auth_ok')).toMatchObject({ color: 'green', blink: false })
  })
  it('rouge clignotant sur mot de passe erroné', () => {
    expect(ledView('auth_fail')).toMatchObject({ color: 'red', blink: true })
  })
  it('rouge fixe quand non reconnu', () => {
    expect(ledView('not_recognized')).toMatchObject({ color: 'red', blink: false })
  })
})
