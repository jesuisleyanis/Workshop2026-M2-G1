import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import type { FaceScannerProps } from './scanner/FaceScanner'
import { EnrollWizard } from './EnrollWizard'
import { ApiError } from '../api/http'

// FaceScanner mocké : un bouton « termine » les captures (une frame par pose, dans l'ordre).
vi.mock('./scanner/FaceScanner', () => ({
  FaceScanner: (props: FaceScannerProps) => (
    <div data-testid="scanner" data-mode={props.mode} data-poses={props.poses.join(',')}>
      <button type="button" onClick={() => props.onComplete(props.poses.map((pose) => ({ pose, image_b64: `IMG_${pose}` })))}>
        terminer le scan
      </button>
      {props.onCancel && (
        <button type="button" onClick={props.onCancel}>
          annuler le scan
        </button>
      )}
    </div>
  ),
}))
vi.mock('../api/admin', async (orig) => {
  const actual = await orig<typeof import('../api/admin')>()
  return { ...actual, createUser: vi.fn(), enrollFace: vi.fn() }
})
import { createUser, enrollFace } from '../api/admin'
const mCreate = createUser as unknown as Mock
const mEnroll = enrollFace as unknown as Mock

const POSES = { face: 'IMG_face', gauche: 'IMG_gauche', droite: 'IMG_droite' }
const rejected = (details: { pose: string; reason: string }[]) =>
  new ApiError(422, 'enrollment_rejected', 'rejet', undefined, details)

let user: ReturnType<typeof userEvent.setup>
beforeEach(() => {
  vi.clearAllMocks()
  user = userEvent.setup()
  mCreate.mockResolvedValue({ username: 'alice', role: 'operator' })
  mEnroll.mockResolvedValue({ enrolled: true, model_version: 1 })
})

function renderWizard(props: Partial<ComponentProps<typeof EnrollWizard>> = {}) {
  const onClose = vi.fn()
  render(<EnrollWizard token="tok" onClose={onClose} {...props} />)
  return onClose
}

async function fillForm(over: { username?: string; password?: string; confirm?: string; role?: string } = {}) {
  await user.type(screen.getByLabelText(/^identifiant/i), over.username ?? 'alice')
  await user.type(screen.getByLabelText(/^mot de passe/i), over.password ?? 'Secret123')
  await user.type(screen.getByLabelText(/confirmation/i), over.confirm ?? over.password ?? 'Secret123')
  if (over.role) await user.selectOptions(screen.getByLabelText(/rôle/i), over.role)
  await user.click(screen.getByRole('button', { name: /continuer/i }))
}

const scanAndValidate = async () => {
  await user.click(await screen.findByRole('button', { name: /terminer le scan/i }))
  await user.click(await screen.findByRole('button', { name: /valider l.enrôlement/i }))
}

describe('EnrollWizard — étape 1 : compte', () => {
  it('refuse un identifiant invalide sans passer au scanner', async () => {
    renderWizard()
    await fillForm({ username: 'a b' })
    expect(await screen.findByText(/identifiant invalide/i)).toBeInTheDocument()
    expect(screen.queryByTestId('scanner')).not.toBeInTheDocument()
  })

  it('refuse un mot de passe trop court (< 8 octets)', async () => {
    renderWizard()
    await fillForm({ password: 'court' })
    expect(await screen.findByText(/trop court/i)).toBeInTheDocument()
    expect(screen.queryByTestId('scanner')).not.toBeInTheDocument()
  })

  it('refuse un mot de passe de plus de 72 octets UTF-8', async () => {
    renderWizard()
    await fillForm({ password: 'é'.repeat(37) }) // 74 octets
    expect(await screen.findByText(/trop long/i)).toBeInTheDocument()
  })

  it('refuse deux mots de passe différents', async () => {
    renderWizard()
    await fillForm({ password: 'Secret123', confirm: 'Secret124' })
    expect(await screen.findByText(/ne correspondent pas/i)).toBeInTheDocument()
    expect(screen.queryByTestId('scanner')).not.toBeInTheDocument()
  })

  it('signale tout de suite un identifiant déjà présent dans la liste', async () => {
    renderWizard({ takenUsernames: ['Alice'] })
    await fillForm({ username: 'alice' })
    expect(await screen.findByText(/déjà utilisé/i)).toBeInTheDocument()
    expect(screen.queryByTestId('scanner')).not.toBeInTheDocument()
  })

  it('propose les trois rôles', () => {
    renderWizard()
    const options = within(screen.getByLabelText(/rôle/i)).getAllByRole('option')
    expect(options.map((o) => (o as HTMLOptionElement).value)).toEqual(['customer', 'operator', 'admin'])
  })
})

describe('EnrollWizard — scan, récapitulatif, validation', () => {
  it('scanner en mode enroll avec les trois poses, puis récapitulatif et création + enrôlement', async () => {
    const onClose = renderWizard()
    await fillForm({ role: 'operator' })
    const scanner = await screen.findByTestId('scanner')
    expect(scanner).toHaveAttribute('data-mode', 'enroll')
    expect(scanner).toHaveAttribute('data-poses', 'face,gauche,droite')

    await user.click(screen.getByRole('button', { name: /terminer le scan/i }))
    // Récapitulatif : vignettes des images capturées, scanner (et caméra) démonté.
    expect(await screen.findByAltText(/photo face/i)).toHaveAttribute('src', 'data:image/jpeg;base64,IMG_face')
    expect(screen.getByAltText(/photo gauche/i)).toHaveAttribute('src', 'data:image/jpeg;base64,IMG_gauche')
    expect(screen.getByAltText(/photo droite/i)).toHaveAttribute('src', 'data:image/jpeg;base64,IMG_droite')
    expect(screen.queryByTestId('scanner')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /valider l.enrôlement/i }))
    await vi.waitFor(() => expect(onClose).toHaveBeenCalledWith(true))
    expect(mCreate).toHaveBeenCalledWith('tok', { username: 'alice', password: 'Secret123', role: 'operator' })
    expect(mEnroll).toHaveBeenCalledWith('tok', 'alice', POSES)
    expect(mCreate.mock.invocationCallOrder[0]!).toBeLessThan(mEnroll.mock.invocationCallOrder[0]!)
  })

  it('rejet 422 : détails par pose en français et reprise des 3 poses (sans recréer le compte)', async () => {
    const onClose = renderWizard()
    mEnroll.mockRejectedValueOnce(
      rejected([
        { pose: 'gauche', reason: 'wrong_pose' },
        { pose: 'face', reason: 'no_face' },
        { pose: 'droite', reason: 'inconsistent' },
      ]),
    )
    await fillForm()
    await scanAndValidate()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/gauche/i)
    expect(alert).toHaveTextContent('pose incorrecte')
    expect(alert).toHaveTextContent('aucun visage')
    expect(alert).toHaveTextContent('pas la même personne')
    // Retour au scanner pour reprendre les trois poses.
    expect(await screen.findByTestId('scanner')).toHaveAttribute('data-poses', 'face,gauche,droite')
    expect(onClose).not.toHaveBeenCalled()

    await scanAndValidate()
    await vi.waitFor(() => expect(onClose).toHaveBeenCalledWith(true))
    expect(mCreate).toHaveBeenCalledTimes(1)
    expect(mEnroll).toHaveBeenCalledTimes(2)
  })

  it('libellés français pour multiple_faces et invalid_image', async () => {
    renderWizard()
    mEnroll.mockRejectedValueOnce(
      rejected([
        { pose: 'face', reason: 'multiple_faces' },
        { pose: 'droite', reason: 'invalid_image' },
      ]),
    )
    await fillForm()
    await scanAndValidate()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('plusieurs visages')
    expect(alert).toHaveTextContent('image illisible')
  })

  it('identifiant déjà pris (409) : retour à l’étape compte avec le message', async () => {
    renderWizard()
    mCreate.mockRejectedValueOnce(new ApiError(409, 'username_taken', 'pris'))
    await fillForm()
    await scanAndValidate()
    expect(await screen.findByText(/déjà utilisé/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^identifiant/i)).toBeInTheDocument()
    expect(mEnroll).not.toHaveBeenCalled()
  })

  it('service de reconnaissance indisponible (503) : message, récapitulatif conservé, nouvel essai sans recréer le compte', async () => {
    const onClose = renderWizard()
    mEnroll.mockRejectedValueOnce(new ApiError(503, 'face_service_unavailable', 'down'))
    await fillForm()
    await scanAndValidate()
    expect(await screen.findByRole('alert')).toHaveTextContent(/indisponible/i)
    await user.click(screen.getByRole('button', { name: /valider l.enrôlement/i }))
    await vi.waitFor(() => expect(onClose).toHaveBeenCalledWith(true))
    expect(mCreate).toHaveBeenCalledTimes(1)
  })

  it('annuler au scan ferme sans rafraîchir si rien n’a été créé', async () => {
    const onClose = renderWizard()
    await fillForm()
    await user.click(await screen.findByRole('button', { name: /annuler le scan/i }))
    expect(onClose).toHaveBeenCalledWith(false)
    expect(mCreate).not.toHaveBeenCalled()
  })

  it('annuler après création du compte demande le rafraîchissement de la liste', async () => {
    const onClose = renderWizard()
    mEnroll.mockRejectedValueOnce(new ApiError(503, 'face_service_unavailable', 'down'))
    await fillForm()
    await scanAndValidate()
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: /annuler/i }))
    expect(onClose).toHaveBeenCalledWith(true)
  })
})

describe('EnrollWizard — ré-enrôlement', () => {
  it('saute le formulaire et n’appelle que enrollFace', async () => {
    const onClose = renderWizard({ reenroll: 'bob' })
    expect(await screen.findByTestId('scanner')).toBeInTheDocument()
    expect(screen.getByText(/bob/)).toBeInTheDocument()
    await scanAndValidate()
    await vi.waitFor(() => expect(onClose).toHaveBeenCalledWith(true))
    expect(mCreate).not.toHaveBeenCalled()
    expect(mEnroll).toHaveBeenCalledWith('tok', 'bob', POSES)
  })
})
