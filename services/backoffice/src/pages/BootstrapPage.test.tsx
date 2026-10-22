import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { FaceScannerProps } from '../components/scanner/FaceScanner'
import { BootstrapPage } from './BootstrapPage'
import { ApiError } from '../api/http'

vi.mock('../components/scanner/FaceScanner', () => ({
  FaceScanner: (props: FaceScannerProps) => (
    <div data-testid="scanner" data-mode={props.mode} data-poses={props.poses.join(',')}>
      <button type="button" onClick={() => props.onComplete(props.poses.map((pose) => ({ pose, image_b64: `IMG_${pose}` })))}>
        terminer le scan
      </button>
    </div>
  ),
}))
vi.mock('../api/auth', async (orig) => {
  const actual = await orig<typeof import('../api/auth')>()
  return { ...actual, bootstrap: vi.fn() }
})
import { bootstrap } from '../api/auth'
const mBootstrap = bootstrap as unknown as Mock

let user: ReturnType<typeof userEvent.setup>
beforeEach(() => {
  vi.clearAllMocks()
  user = userEvent.setup()
  mBootstrap.mockResolvedValue({ username: 'root', role: 'admin' })
})

async function fillForm(over: { token?: string; username?: string; password?: string; confirm?: string } = {}) {
  await user.type(screen.getByLabelText(/jeton d.initialisation/i), over.token ?? 'init-token')
  await user.type(screen.getByLabelText(/^identifiant/i), over.username ?? 'root')
  await user.type(screen.getByLabelText(/^mot de passe/i), over.password ?? 'Secret123')
  await user.type(screen.getByLabelText(/confirmation/i), over.confirm ?? over.password ?? 'Secret123')
  await user.click(screen.getByRole('button', { name: /continuer/i }))
}

async function scanAndValidate() {
  await user.click(await screen.findByRole('button', { name: /terminer le scan/i }))
  await user.click(await screen.findByRole('button', { name: /valider l.enrôlement/i }))
}

describe('BootstrapPage — initialisation du back-office', () => {
  it('affiche la carte d’initialisation (conserve le test id racine)', () => {
    render(<BootstrapPage onDone={vi.fn()} />)
    expect(screen.getByTestId('bootstrap-page')).toBeInTheDocument()
    expect(screen.getByText(/initialisation du back-office/i)).toBeInTheDocument()
  })

  it('valide les champs : jeton requis, identifiant valide', async () => {
    render(<BootstrapPage onDone={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: /continuer/i }))
    expect(await screen.findByText(/jeton d.initialisation requis/i)).toBeInTheDocument()
    expect(screen.getByText(/identifiant invalide/i)).toBeInTheDocument()
    expect(screen.queryByTestId('scanner')).not.toBeInTheDocument()
  })

  it('mots de passe différents : pas de scanner', async () => {
    render(<BootstrapPage onDone={vi.fn()} />)
    await fillForm({ password: 'Secret123', confirm: 'autre-chose' })
    expect(await screen.findByText(/ne correspondent pas/i)).toBeInTheDocument()
    expect(screen.queryByTestId('scanner')).not.toBeInTheDocument()
  })

  it('succès : scanner enroll, bootstrap() avec jeton, identifiant, mot de passe et poses, puis callback', async () => {
    const onDone = vi.fn()
    render(<BootstrapPage onDone={onDone} />)
    await fillForm()
    expect(await screen.findByTestId('scanner')).toHaveAttribute('data-mode', 'enroll')
    expect(screen.getByTestId('scanner')).toHaveAttribute('data-poses', 'face,gauche,droite')
    await scanAndValidate()

    await vi.waitFor(() =>
      expect(mBootstrap).toHaveBeenCalledWith({
        token: 'init-token',
        username: 'root',
        password: 'Secret123',
        poses: { face: 'IMG_face', gauche: 'IMG_gauche', droite: 'IMG_droite' },
      }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent(/administrateur créé/i)
    expect(onDone).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: /aller à la connexion/i }))
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('jeton faux (403 bootstrap_denied) : message et retour au formulaire', async () => {
    const onDone = vi.fn()
    render(<BootstrapPage onDone={onDone} />)
    mBootstrap.mockRejectedValueOnce(new ApiError(403, 'bootstrap_denied', 'denied'))
    await fillForm({ token: 'faux' })
    await scanAndValidate()
    expect(await screen.findByText(/jeton d.initialisation invalide/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/jeton d.initialisation/i)).toBeInTheDocument()
    expect(onDone).not.toHaveBeenCalled()
  })

  it('rejet 422 : détails par pose et reprise du scan', async () => {
    render(<BootstrapPage onDone={vi.fn()} />)
    mBootstrap.mockRejectedValueOnce(new ApiError(422, 'enrollment_rejected', 'rejet', undefined, [{ pose: 'droite', reason: 'no_face' }]))
    await fillForm()
    await scanAndValidate()
    expect(await screen.findByRole('alert')).toHaveTextContent('aucun visage')
    expect(await screen.findByTestId('scanner')).toBeInTheDocument()
  })
})
