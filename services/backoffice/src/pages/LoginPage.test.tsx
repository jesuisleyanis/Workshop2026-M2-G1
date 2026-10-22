import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { FaceScannerProps } from '../components/scanner/FaceScanner'
import { LoginPage, GRANTED_DELAY_MS, RECOGNIZED_DELAY_MS } from './LoginPage'
import { AuthError } from '../api/auth'

// FaceScanner mocké : expose les props utiles et un bouton qui « termine » les captures
// (une frame par pose demandée, dans l'ordre du serveur). Les enfants (décompte) sont rendus.
vi.mock('../components/scanner/FaceScanner', () => ({
  FaceScanner: (props: FaceScannerProps) => (
    <div data-testid="scanner" data-poses={props.poses.join(',')} data-verdict={props.verdict ?? 'idle'}>
      <button type="button" onClick={() => props.onComplete(props.poses.map((pose) => ({ pose, image_b64: `IMG_${pose}` })))}>
        terminer le scan
      </button>
      {props.children}
    </div>
  ),
}))

// API auth mockée (AuthError réel pour les branches d'erreur).
vi.mock('../api/auth', async (orig) => {
  const actual = await orig<typeof import('../api/auth')>()
  return {
    ...actual,
    identify: vi.fn(),
    verifyFace: vi.fn(),
    submitPassword: vi.fn(),
    deviceStatus: vi.fn(),
  }
})
import { deviceStatus, identify, submitPassword, verifyFace } from '../api/auth'

const mIdentify = identify as unknown as Mock
const mVerify = verifyFace as unknown as Mock
const mPassword = submitPassword as unknown as Mock
const mDevice = deviceStatus as unknown as Mock

const POSES = ['gauche', 'face', 'droite'] as const
const FACE_CHALLENGE = { challenge_id: 'c1', step: 'face' as const, expires_in: 120, camera: true, poses: [...POSES] }
const RECOGNIZED = { recognized: true, step: 'password', attempts_left: 2, cooldown: 0 }
const TOKEN = { access_token: 'jwt', token_type: 'bearer', expires_in: 900, role: 'operator' }

// Horloge factice qui avance aussi en temps réel : findBy*/waitFor restent utilisables, et
// advance() saute les refroidissements (30 s, 3 s, 5 min) sans attendre.
let user: ReturnType<typeof userEvent.setup>
beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.clearAllMocks()
  mDevice.mockResolvedValue({ led_online: true })
  user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
})
afterEach(() => {
  vi.useRealTimers()
})

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

async function renderLogin(onAuthenticated = vi.fn()) {
  render(<LoginPage onAuthenticated={onAuthenticated} />)
  // Le statut du module LED arrive de façon asynchrone : on l'attend pour un rendu stable.
  await screen.findByText('Module LED en ligne')
  return onAuthenticated
}

const usernameField = () => screen.getByRole('textbox', { name: /identifiant/i }) as HTMLInputElement
const led = () => screen.getByTestId('led')

async function reachScan() {
  mIdentify.mockResolvedValue(FACE_CHALLENGE)
  await user.type(usernameField(), 'op01')
  await user.click(screen.getByRole('button', { name: /continuer/i }))
  return screen.findByTestId('scanner')
}

async function reachPassword() {
  await reachScan()
  mVerify.mockResolvedValue(RECOGNIZED)
  await user.click(screen.getByRole('button', { name: /terminer le scan/i }))
  await advance(RECOGNIZED_DELAY_MS)
  return screen.findByLabelText(/mot de passe/i)
}

describe('LoginPage v2 — mise en page du front', () => {
  it('panneau nuit : titre, sous-texte et statut du module LED', async () => {
    await renderLogin()
    expect(screen.getByText('Accès back-office')).toBeInTheDocument()
    expect(screen.getByText('Authentification renforcée : identifiant, visage, mot de passe.')).toBeInTheDocument()
    expect(led().getAttribute('data-led')).toBe('idle')
    expect(usernameField()).toHaveFocus()
  })

  it('statut LED hors ligne / inconnu', async () => {
    mDevice.mockResolvedValue({ led_online: false })
    render(<LoginPage onAuthenticated={vi.fn()} />)
    expect(await screen.findByText('Module LED hors ligne')).toBeInTheDocument()
  })

  it('statut LED inconnu si le module ne répond pas', async () => {
    mDevice.mockRejectedValue(new AuthError(0, 'network_error', 'x'))
    render(<LoginPage onAuthenticated={vi.fn()} />)
    expect(await screen.findByText('Module LED inconnu')).toBeInTheDocument()
  })
})

describe('LoginPage v2 — ordre des étapes', () => {
  it("impose le visage avant le mot de passe et transmet les poses du serveur", async () => {
    await renderLogin()
    const scanner = await reachScan()
    expect(mIdentify).toHaveBeenCalledWith('op01')
    expect(scanner.getAttribute('data-poses')).toBe('gauche,face,droite')
    // Étape visage : aucun champ mot de passe.
    expect(screen.queryByLabelText(/mot de passe/i)).toBeNull()

    mVerify.mockResolvedValue(RECOGNIZED)
    await user.click(screen.getByRole('button', { name: /terminer le scan/i }))
    expect(mVerify).toHaveBeenCalledWith('c1', [
      { pose: 'gauche', image_b64: 'IMG_gauche' },
      { pose: 'face', image_b64: 'IMG_face' },
      { pose: 'droite', image_b64: 'IMG_droite' },
    ])
    expect((await screen.findByTestId('scanner')).getAttribute('data-verdict')).toBe('granted')
    expect(led().getAttribute('data-led')).toBe('recognized')

    await advance(RECOGNIZED_DELAY_MS)
    const pwd = await screen.findByLabelText(/mot de passe/i)
    expect(screen.queryByTestId('scanner')).toBeNull() // caméra coupée (scanner démonté)
    expect(pwd).toHaveFocus()
  })

  it('succès : écran accordé puis onAuthenticated après 1,5 s', async () => {
    const onAuth = await renderLogin()
    const pwd = await reachPassword()
    mPassword.mockResolvedValue(TOKEN)
    await user.type(pwd, 'secret')
    await user.click(screen.getByRole('button', { name: /se connecter/i }))

    expect(mPassword).toHaveBeenCalledWith('c1', 'secret')
    expect(await screen.findByText(/accès autorisé/i, { selector: 'h1' })).toBeInTheDocument()
    expect(led().getAttribute('data-led')).toBe('auth_ok')
    expect(onAuth).not.toHaveBeenCalled()
    await advance(GRANTED_DELAY_MS)
    expect(onAuth).toHaveBeenCalledWith(TOKEN)
  })
})

describe('LoginPage v2 — refroidissements', () => {
  it('visage refusé : caméra gardée 30 s avec décompte, puis identifiant vidé', async () => {
    await renderLogin()
    await reachScan()
    mVerify.mockResolvedValue({ recognized: false, step: 'identify', attempts_left: 1, cooldown: 30 })
    await user.click(screen.getByRole('button', { name: /terminer le scan/i }))

    const scanner = await screen.findByTestId('scanner')
    expect(scanner.getAttribute('data-verdict')).toBe('denied')
    expect(scanner).toHaveTextContent('Nouvelle tentative dans 30 s')
    expect(screen.getByRole('alert')).toHaveTextContent(/non reconnu/i)
    expect(led().getAttribute('data-led')).toBe('not_recognized')

    await advance(29_000)
    expect(screen.getByTestId('scanner')).toHaveTextContent('Nouvelle tentative dans 1 s')

    await advance(1_000)
    expect(screen.queryByTestId('scanner')).toBeNull()
    expect(usernameField().value).toBe('')
    expect(usernameField()).toHaveFocus()
  })

  it('visage refusé sans tentative restante : écran de blocage après le refroidissement', async () => {
    await renderLogin()
    await reachScan()
    mVerify.mockResolvedValue({ recognized: false, step: 'identify', attempts_left: 0, cooldown: 30 })
    await user.click(screen.getByRole('button', { name: /terminer le scan/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/bloqué/i)
    expect(screen.getByTestId('scanner')).toBeInTheDocument() // caméra encore allumée
    await advance(30_000)
    expect(screen.queryByTestId('scanner')).toBeNull()
    expect(screen.getByRole('heading', { name: /accès bloqué/i })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /identifiant/i })).toBeNull()
  })

  it('mot de passe refusé : champ désactivé 3 s puis retour à l’identifiant vidé', async () => {
    await renderLogin()
    const pwd = await reachPassword()
    mPassword.mockRejectedValue(new AuthError(401, 'invalid_credentials', 'bad', 3))
    await user.type(pwd, 'faux')
    await user.click(screen.getByRole('button', { name: /se connecter/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/mot de passe incorrect/i)
    expect(screen.getByLabelText(/mot de passe/i)).toBeDisabled()
    expect(led().getAttribute('data-led')).toBe('auth_fail')

    await advance(3_000)
    expect(screen.queryByLabelText(/mot de passe/i)).toBeNull()
    expect(usernameField().value).toBe('')
    expect(usernameField()).toHaveFocus()
  })

  it('429 locked_out : écran de blocage avec décompte 5 min, puis identifiant', async () => {
    await renderLogin()
    mIdentify.mockRejectedValue(new AuthError(429, 'locked_out', 'locked', 300))
    await user.type(usernameField(), 'op01')
    await user.click(screen.getByRole('button', { name: /continuer/i }))

    expect(await screen.findByRole('heading', { name: /accès bloqué/i })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('5:00')
    await advance(60_000)
    expect(screen.getByRole('alert')).toHaveTextContent('4:00')
    await advance(240_000)
    expect(usernameField().value).toBe('')
  })

  it('429 cooldown : décompte Retry-After sur l’écran identifiant', async () => {
    await renderLogin()
    mIdentify.mockRejectedValue(new AuthError(429, 'cooldown', 'wait', 12))
    await user.type(usernameField(), 'op01')
    await user.click(screen.getByRole('button', { name: /continuer/i }))

    const btn = await screen.findByRole('button', { name: /patientez 12 s/i })
    expect(btn).toBeDisabled()
    await advance(12_000)
    expect(screen.getByRole('button', { name: /continuer/i })).toBeEnabled()
  })
})

describe('LoginPage v2 — erreurs', () => {
  it('rôle non autorisé : message explicite et retour à l’identifiant', async () => {
    await renderLogin()
    const pwd = await reachPassword()
    mPassword.mockRejectedValue(new AuthError(403, 'role_not_authorized', 'no'))
    await user.type(pwd, 'secret')
    await user.click(screen.getByRole('button', { name: /se connecter/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/pas autorisé/i)
    expect(usernameField().value).toBe('')
  })

  it('service visage indisponible : retour à l’identifiant avec message', async () => {
    await renderLogin()
    await reachScan()
    mVerify.mockRejectedValue(new AuthError(503, 'face_service_unavailable', 'down'))
    await user.click(screen.getByRole('button', { name: /terminer le scan/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/indisponible/i)
    expect(screen.queryByTestId('scanner')).toBeNull()
  })
})
