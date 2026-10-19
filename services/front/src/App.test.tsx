import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { App } from './App'
import { AuthProvider } from './components/AuthProvider'
import { fakeJwt, jsonResponse, stubFetch } from './test/helpers'
import { tokenStore } from './api/tokenStore'

const ACCOUNTS = [{ id: 'FR01', label: 'Compte courant', balance: 1250.5, currency: 'EUR' }]
const TXS = [
  { id: 't1', from_account: 'FR01', to_account: 'FR99', amount: 20, currency: 'EUR', status: 'created', label: 'Loyer', created_at: '2026-10-21T09:14:33Z' },
  { id: 't2', from_account: 'FR01', to_account: 'FR98', amount: 9999, currency: 'EUR', status: 'rejected', created_at: '2026-10-21T09:15:00Z' },
]

function renderApp(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

function loginAsStored() {
  tokenStore.set(fakeJwt(Math.floor(Date.now() / 1000) + 600))
}

describe('Front - parcours', () => {
  it('redirige vers /login sans jeton', () => {
    renderApp('/history')
    expect(screen.getByRole('heading', { name: 'Connexion' })).toBeInTheDocument()
  })

  it('login réussi : stocke le JWT et affiche le tableau de bord avec le solde', async () => {
    const jwt = fakeJwt(Math.floor(Date.now() / 1000) + 600)
    stubFetch({
      'POST /api/v1/login': () => jsonResponse({ access_token: jwt, token_type: 'bearer' }),
      'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS),
      'GET /api/v1/transactions': () => jsonResponse(TXS),
    })
    renderApp('/login')
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Identifiant'), 'demo01')
    await user.type(screen.getByLabelText('Mot de passe'), 'secret')
    await user.click(screen.getByRole('button', { name: 'Se connecter' }))

    expect(await screen.findByTestId('balance')).toHaveTextContent(/1\s?250,50/)
    expect(tokenStore.get()).toBe(jwt)
    expect(await screen.findByText('Loyer')).toBeInTheDocument()
  })

  it('login refusé : affiche le message et ne stocke rien', async () => {
    stubFetch({
      'POST /api/v1/login': () => jsonResponse({ error: { code: 'invalid_credentials', message: 'Bad' } }, 401),
    })
    renderApp('/login')
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Identifiant'), 'demo01')
    await user.type(screen.getByLabelText('Mot de passe'), 'faux')
    await user.click(screen.getByRole('button', { name: 'Se connecter' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Identifiant ou mot de passe incorrect.')
    expect(tokenStore.get()).toBeNull()
  })

  it('tableau de bord : état de chargement puis erreur avec réessai', async () => {
    loginAsStored()
    let calls = 0
    stubFetch({
      'GET /api/v1/accounts': () => (++calls === 1 ? jsonResponse({ error: { code: 'db_error', message: 'DB down' } }, 503) : jsonResponse(ACCOUNTS)),
      'GET /api/v1/transactions': () => jsonResponse([]),
    })
    renderApp('/')
    expect(screen.getByText('Chargement des comptes…')).toBeInTheDocument()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('DB down')
    await userEvent.click(screen.getByRole('button', { name: 'Réessayer' }))
    expect(await screen.findByTestId('balance')).toBeInTheDocument()
  })

  it('401 sur une page protégée => retour au login et jeton effacé', async () => {
    loginAsStored()
    stubFetch({
      'GET /api/v1/accounts': () => jsonResponse({ error: { code: 'token_expired', message: 'x' } }, 401),
      'GET /api/v1/transactions': () => jsonResponse({ error: { code: 'token_expired', message: 'x' } }, 401),
    })
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'Connexion' })).toBeInTheDocument()
    expect(tokenStore.get()).toBeNull()
  })

  it('virement : validation client puis envoi POST /api/v1/transactions', async () => {
    loginAsStored()
    const fetchMock = stubFetch({
      'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS),
      'POST /api/v1/transactions': () =>
        jsonResponse({ id: 'n1', from_account: 'FR01', to_account: 'FR77', amount: 25.5, currency: 'EUR', status: 'created', created_at: '2026-10-21T10:00:00Z' }, 201),
    })
    renderApp('/transfer')
    const user = userEvent.setup()
    await screen.findByLabelText('Compte à débiter')

    await user.click(screen.getByRole('button', { name: 'Envoyer le virement' }))
    expect(screen.getByText('Indiquez le compte bénéficiaire.')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([, i]) => (i as RequestInit | undefined)?.method === 'POST')).toBe(false)

    await user.type(screen.getByLabelText('Compte bénéficiaire'), 'FR77')
    await user.type(screen.getByLabelText('Montant'), '25,50')
    await user.click(screen.getByRole('button', { name: 'Envoyer le virement' }))

    expect(await screen.findByRole('status')).toHaveTextContent(/Virement accepté/)
    const post = fetchMock.mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === 'POST')!
    expect(JSON.parse((post[1] as RequestInit).body as string)).toMatchObject({ from_account: 'FR01', to_account: 'FR77', amount: 25.5 })
  })

  it('virement refusé par le serveur : affiche le message métier', async () => {
    loginAsStored()
    stubFetch({
      'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS),
      'POST /api/v1/transactions': () => jsonResponse({ error: { code: 'insufficient_funds', message: 'x' } }, 422),
    })
    renderApp('/transfer')
    const user = userEvent.setup()
    await screen.findByLabelText('Compte à débiter')
    await user.type(screen.getByLabelText('Compte bénéficiaire'), 'FR77')
    await user.type(screen.getByLabelText('Montant'), '10')
    await user.click(screen.getByRole('button', { name: 'Envoyer le virement' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Solde insuffisant pour ce virement.'))
  })

  it('historique : liste les transactions avec leur statut', async () => {
    loginAsStored()
    stubFetch({ 'GET /api/v1/transactions': () => jsonResponse(TXS) })
    renderApp('/history')
    expect(await screen.findByText('Acceptée')).toBeInTheDocument()
    expect(screen.getByText('Refusée')).toBeInTheDocument()
  })
})
