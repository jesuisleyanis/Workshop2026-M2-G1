import { describe, expect, it, vi, beforeEach, type Mock } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoginPage } from './LoginPage'
import { AuthError } from '../api/auth'

// Caméra mockée (getUserMedia non implémenté dans jsdom) : capture déterministe.
const cam = vi.hoisted(() => ({
  start: vi.fn(() => Promise.resolve()),
  capture: vi.fn(() => 'IMG_B64'),
  stop: vi.fn(),
  videoRef: { current: null },
}))
vi.mock('../hooks/useCamera', () => ({ useCamera: () => cam }))

// API auth mockée (on garde AuthError réel pour les branches d'erreur).
vi.mock('../api/auth', async (orig) => {
  const actual = await orig<typeof import('../api/auth')>()
  return { ...actual, identify: vi.fn(), verifyFace: vi.fn(), submitPassword: vi.fn() }
})
import { identify, verifyFace, submitPassword } from '../api/auth'

const mIdentify = identify as unknown as Mock
const mVerify = verifyFace as unknown as Mock
const mPassword = submitPassword as unknown as Mock

const FACE_CHALLENGE = { challenge_id: 'c1', step: 'face' as const, expires_in: 60, camera: true }

beforeEach(() => {
  vi.clearAllMocks()
  cam.start.mockResolvedValue(undefined)
})

async function reachScanning(user: ReturnType<typeof userEvent.setup>) {
  mIdentify.mockResolvedValue(FACE_CHALLENGE)
  await user.type(screen.getByRole('textbox', { name: /identifiant/i }), 'op01')
  await user.click(screen.getByRole('button', { name: /continuer/i }))
  await screen.findByTestId('camera')
}

describe('LoginPage — login à étapes', () => {
  it("n'affiche le mot de passe qu'après reconnaissance du visage (ordre imposé)", async () => {
    const user = userEvent.setup()
    render(<LoginPage onAuthenticated={vi.fn()} />)
    await reachScanning(user)
    // À l'étape scan : pas de champ mot de passe.
    expect(screen.queryByLabelText(/mot de passe/i)).toBeNull()
    expect(cam.start).toHaveBeenCalled()

    mVerify.mockResolvedValue({ recognized: true, step: 'password', attempts_left: 2 })
    await user.click(screen.getByRole('button', { name: /scanner/i }))

    expect(await screen.findByLabelText(/mot de passe/i)).toBeInTheDocument()
    expect(cam.stop).toHaveBeenCalled()
    expect(screen.getByTestId('led').getAttribute('data-led')).toBe('recognized')
  })

  it('vide l’identifiant et affiche un message quand le visage est rejeté', async () => {
    const user = userEvent.setup()
    render(<LoginPage onAuthenticated={vi.fn()} />)
    await reachScanning(user)

    mVerify.mockResolvedValue({ recognized: false, step: 'face', attempts_left: 1 })
    await user.click(screen.getByRole('button', { name: /scanner/i }))

    // Retour à l'identification : champ vidé + alerte + LED rouge fixe.
    const field = (await screen.findByRole('textbox', { name: /identifiant/i })) as HTMLInputElement
    expect(field.value).toBe('')
    expect(screen.getByRole('alert').textContent).toMatch(/non reconnu/i)
    expect(screen.getByTestId('led').getAttribute('data-led')).toBe('not_recognized')
  })

  it('va au bout : mot de passe correct déclenche onAuthenticated', async () => {
    const user = userEvent.setup()
    const onAuth = vi.fn()
    render(<LoginPage onAuthenticated={onAuth} />)
    await reachScanning(user)
    mVerify.mockResolvedValue({ recognized: true, step: 'password', attempts_left: 2 })
    await user.click(screen.getByRole('button', { name: /scanner/i }))

    mPassword.mockResolvedValue({ access_token: 'jwt', token_type: 'bearer', expires_in: 900, role: 'operator' })
    await user.type(await screen.findByLabelText(/mot de passe/i), 'secret')
    await user.click(screen.getByRole('button', { name: /se connecter/i }))

    await waitFor(() => expect(onAuth).toHaveBeenCalledWith(expect.objectContaining({ role: 'operator' })))
  })

  it('affiche le blocage 5 min sur un 429', async () => {
    const user = userEvent.setup()
    mIdentify.mockRejectedValue(new AuthError(429, 'locked_out', 'locked', 300))
    render(<LoginPage onAuthenticated={vi.fn()} />)
    await user.type(screen.getByRole('textbox', { name: /identifiant/i }), 'op01')
    await user.click(screen.getByRole('button', { name: /continuer/i }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/bloqué/i)
  })

  it('refuse un rôle non autorisé après mot de passe correct', async () => {
    const user = userEvent.setup()
    render(<LoginPage onAuthenticated={vi.fn()} />)
    await reachScanning(user)
    mVerify.mockResolvedValue({ recognized: true, step: 'password', attempts_left: 2 })
    await user.click(screen.getByRole('button', { name: /scanner/i }))
    mPassword.mockRejectedValue(new AuthError(403, 'role_not_authorized', 'no'))
    await user.type(await screen.findByLabelText(/mot de passe/i), 'secret')
    await user.click(screen.getByRole('button', { name: /se connecter/i }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/pas autorisé/i)
  })
})
