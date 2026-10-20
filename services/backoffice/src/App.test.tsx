import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { getSession } from './lib/session'

// LoginPage mocké : un bouton simule une authentification réussie.
vi.mock('./pages/LoginPage', () => ({
  LoginPage: ({ onAuthenticated }: { onAuthenticated: (t: unknown) => void }) => (
    <button
      type="button"
      onClick={() => onAuthenticated({ access_token: 'jwt', token_type: 'bearer', expires_in: 900, role: 'admin' })}
    >
      login simulé
    </button>
  ),
}))
vi.mock('./api/auth', async (orig) => {
  const actual = await orig<typeof import('./api/auth')>()
  return { ...actual, bootstrapStatus: vi.fn() }
})
import { bootstrapStatus } from './api/auth'
const mBootstrap = bootstrapStatus as unknown as Mock

beforeEach(() => {
  vi.clearAllMocks()
})

describe('App — routage bootstrap / login / accueil', () => {
  it('affiche le bootstrap quand aucun admin n’existe', async () => {
    mBootstrap.mockResolvedValue({ required: true })
    render(<App />)
    expect(await screen.findByTestId('bootstrap-page')).toBeInTheDocument()
  })

  it('affiche le login puis l’accueil une fois authentifié (session en mémoire)', async () => {
    mBootstrap.mockResolvedValue({ required: false })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: /login simulé/i }))
    expect(await screen.findByTestId('home-page')).toBeInTheDocument()
    expect(getSession()?.role).toBe('admin')

    await userEvent.click(screen.getByRole('button', { name: /se déconnecter/i }))
    expect(await screen.findByRole('button', { name: /login simulé/i })).toBeInTheDocument()
    expect(getSession()).toBeNull()
  })

  it('statut bootstrap injoignable : login par défaut', async () => {
    mBootstrap.mockRejectedValue(new Error('down'))
    render(<App />)
    expect(await screen.findByRole('button', { name: /login simulé/i })).toBeInTheDocument()
  })
})
