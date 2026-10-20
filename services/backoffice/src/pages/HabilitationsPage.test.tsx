import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HabilitationsPage } from './HabilitationsPage'
import { ApiError } from '../api/http'
import type { AgentRow } from '../api/admin'

// Assistant mocké : expose ses props et permet de simuler la fermeture.
vi.mock('../components/EnrollWizard', () => ({
  EnrollWizard: (props: { reenroll?: string; takenUsernames?: string[]; onClose: (refresh: boolean) => void }) => (
    <div data-testid="wizard" data-reenroll={props.reenroll ?? ''} data-taken={(props.takenUsernames ?? []).join(',')}>
      <button type="button" onClick={() => props.onClose(true)}>
        fermer l’assistant
      </button>
    </div>
  ),
}))
vi.mock('../api/admin', async (orig) => {
  const actual = await orig<typeof import('../api/admin')>()
  return { ...actual, listUsers: vi.fn(), setRole: vi.fn(), revokeFace: vi.fn(), facePhotos: vi.fn() }
})
import { facePhotos, listUsers, revokeFace, setRole } from '../api/admin'
const mList = listUsers as unknown as Mock
const mSetRole = setRole as unknown as Mock
const mRevoke = revokeFace as unknown as Mock
const mPhotos = facePhotos as unknown as Mock

const ROWS: AgentRow[] = [
  { username: 'alice', role: 'admin', enrolled: true, enrolled_at: '2026-10-20T10:00:00Z', enrolled_by: 'root' },
  { username: 'bob', role: 'operator', enrolled: false, enrolled_at: null, enrolled_by: null },
]

let user: ReturnType<typeof userEvent.setup>
beforeEach(() => {
  vi.clearAllMocks()
  user = userEvent.setup()
  mList.mockResolvedValue(ROWS)
})

async function renderPage(onUnauthorized = vi.fn()) {
  render(<HabilitationsPage token="tok" onUnauthorized={onUnauthorized} />)
  await screen.findByText('alice')
  return onUnauthorized
}

const rowOf = (name: string) => screen.getByRole('row', { name: new RegExp(name) })

describe('HabilitationsPage — liste', () => {
  it('liste les agents avec rôle et statut visage', async () => {
    await renderPage()
    expect(mList).toHaveBeenCalledWith('tok')
    const alice = rowOf('alice')
    expect(within(alice).getByRole('combobox')).toHaveValue('admin')
    expect(alice).toHaveTextContent(/enrôlé le .*20.*par root/i)
    const bob = rowOf('bob')
    expect(within(bob).getByRole('combobox')).toHaveValue('operator')
    expect(bob).toHaveTextContent(/non enrôlé/i)
  })

  it('actions selon l’état : photos/révoquer seulement si enrôlé, (ré-)enrôler toujours', async () => {
    await renderPage()
    expect(screen.getByRole('button', { name: /voir les photos de alice/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /voir les photos de bob/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /révoquer le visage de bob/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^enrôler le visage de bob/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /ré-enrôler le visage de alice/i })).toBeInTheDocument()
  })

  it('erreur de chargement avec bouton Réessayer', async () => {
    mList.mockRejectedValueOnce(new ApiError(0, 'network_error', 'x'))
    render(<HabilitationsPage token="tok" />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/injoignable/i)
    await user.click(screen.getByRole('button', { name: /réessayer/i }))
    expect(await screen.findByText('alice')).toBeInTheDocument()
  })

  it('401 : demande la déconnexion', async () => {
    mList.mockRejectedValueOnce(new ApiError(401, 'http_401', 'x'))
    const onUnauthorized = vi.fn()
    render(<HabilitationsPage token="tok" onUnauthorized={onUnauthorized} />)
    await vi.waitFor(() => expect(onUnauthorized).toHaveBeenCalled())
  })

  it('403 (rôle insuffisant côté serveur) : message d’erreur', async () => {
    mList.mockRejectedValueOnce(new ApiError(403, 'forbidden', 'x'))
    render(<HabilitationsPage token="tok" />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/droits insuffisants/i)
  })
})

describe('HabilitationsPage — rôles', () => {
  it('changer le rôle appelle setRole puis reflète la nouvelle valeur', async () => {
    mSetRole.mockResolvedValue({ username: 'bob', role: 'admin' })
    await renderPage()
    await user.selectOptions(within(rowOf('bob')).getByRole('combobox'), 'admin')
    expect(mSetRole).toHaveBeenCalledWith('tok', 'bob', 'admin')
    await vi.waitFor(() => expect(within(rowOf('bob')).getByRole('combobox')).toHaveValue('admin'))
  })

  it('last_admin : message clair et rôle inchangé', async () => {
    mSetRole.mockRejectedValue(new ApiError(409, 'last_admin', 'x'))
    await renderPage()
    await user.selectOptions(within(rowOf('alice')).getByRole('combobox'), 'operator')
    expect(await screen.findByRole('alert')).toHaveTextContent(/au moins un administrateur/i)
    expect(within(rowOf('alice')).getByRole('combobox')).toHaveValue('admin')
  })
})

describe('HabilitationsPage — révocation et photos', () => {
  it('révocation avec confirmation, puis rechargement de la liste', async () => {
    mRevoke.mockResolvedValue(undefined)
    await renderPage()
    await user.click(screen.getByRole('button', { name: /révoquer le visage de alice/i }))
    // Rien n'est parti tant qu'on n'a pas confirmé.
    expect(mRevoke).not.toHaveBeenCalled()
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveTextContent(/alice/)
    mList.mockResolvedValue([{ ...ROWS[0], enrolled: false, enrolled_at: null, enrolled_by: null }, ROWS[1]])
    await user.click(within(dialog).getByRole('button', { name: /confirmer la révocation/i }))
    expect(mRevoke).toHaveBeenCalledWith('tok', 'alice')
    await vi.waitFor(() => expect(rowOf('alice')).toHaveTextContent(/non enrôlé/i))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('annuler la confirmation n’appelle rien', async () => {
    await renderPage()
    await user.click(screen.getByRole('button', { name: /révoquer le visage de alice/i }))
    await user.click(screen.getByRole('button', { name: /^annuler/i }))
    expect(mRevoke).not.toHaveBeenCalled()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('révocation du dernier admin (409 last_admin) : erreur affichée en clair', async () => {
    mRevoke.mockRejectedValue(new ApiError(409, 'last_admin', 'x'))
    await renderPage()
    await user.click(screen.getByRole('button', { name: /révoquer le visage de alice/i }))
    await user.click(screen.getByRole('button', { name: /confirmer la révocation/i }))
    expect(await screen.findByText(/au moins un administrateur/i)).toBeInTheDocument()
  })

  it('voir les photos : charge facePhotos et affiche trois vignettes', async () => {
    mPhotos.mockResolvedValue({ photos: { face: 'AAA', gauche: 'BBB', droite: 'CCC' } })
    await renderPage()
    await user.click(screen.getByRole('button', { name: /voir les photos de alice/i }))
    expect(mPhotos).toHaveBeenCalledWith('tok', 'alice')
    expect(await screen.findByAltText(/photo gauche/i)).toHaveAttribute('src', 'data:image/jpeg;base64,BBB')
    expect(screen.getByAltText(/photo face/i)).toBeInTheDocument()
    expect(screen.getByAltText(/photo droite/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /masquer les photos/i }))
    expect(screen.queryByAltText(/photo gauche/i)).not.toBeInTheDocument()
  })
})

describe('HabilitationsPage — assistant', () => {
  it('« Nouvel agent » ouvre l’assistant (identifiants existants transmis) ; fermeture => liste rechargée', async () => {
    await renderPage()
    await user.click(screen.getByRole('button', { name: /nouvel agent/i }))
    expect(screen.getByTestId('wizard')).toHaveAttribute('data-reenroll', '')
    expect(screen.getByTestId('wizard')).toHaveAttribute('data-taken', 'alice,bob')
    mList.mockResolvedValue([...ROWS, { username: 'carl', role: 'customer', enrolled: true, enrolled_at: null, enrolled_by: null }])
    await user.click(screen.getByRole('button', { name: /fermer l.assistant/i }))
    expect(await screen.findByText('carl')).toBeInTheDocument()
    expect(screen.queryByTestId('wizard')).not.toBeInTheDocument()
  })

  it('Ré-enrôler ouvre l’assistant sur le compte choisi', async () => {
    await renderPage()
    await user.click(screen.getByRole('button', { name: /ré-enrôler le visage de alice/i }))
    expect(screen.getByTestId('wizard')).toHaveAttribute('data-reenroll', 'alice')
  })
})
