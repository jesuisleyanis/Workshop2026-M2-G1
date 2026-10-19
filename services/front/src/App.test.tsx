import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { App } from './App'
import { AuthProvider } from './components/AuthProvider'
import { fakeJwt, jsonResponse, stubFetch } from './test/helpers'
import { tokenStore } from './api/tokenStore'
import { labelStore } from './lib/labels'

// Fixtures au format réel de payment-api : centimes entiers, ids numériques, src_/dst_account.
const ACCOUNTS = [{ id: 1, iban_fake: 'FR76 0000 0001', balance_cents: 125050, currency: 'EUR' }]
const TWO_ACCOUNTS = [...ACCOUNTS, { id: 2, iban_fake: 'FR76 0000 0002', balance_cents: 5000, currency: 'EUR' }]
const TXS = [
  { id: 1, src_account: 1, dst_account: 99, amount_cents: 2000, status: 'created', label: 'Loyer', created_at: '2026-10-21T09:14:33Z' },
  { id: 2, src_account: 1, dst_account: 98, amount_cents: 999900, status: 'rejected', created_at: '2026-10-21T09:15:00Z' },
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

const posts = (f: ReturnType<typeof stubFetch>) => f.mock.calls.filter(([, i]) => (i as RequestInit | undefined)?.method === 'POST')

describe('Front - connexion', () => {
  it('redirige vers /login sans jeton, avec un message de garde', () => {
    renderApp('/history')
    expect(screen.getByRole('heading', { name: 'Connexion' })).toBeInTheDocument()
    expect(screen.getByText('Connectez-vous pour accéder à cette page.')).toBeInTheDocument()
  })

  it('login réussi : stocke le JWT, affiche solde total, utilisateur (claim sub) et opérations', async () => {
    const jwt = fakeJwt(Math.floor(Date.now() / 1000) + 600)
    stubFetch({
      'POST /api/v1/login': () => jsonResponse({ access_token: jwt, token_type: 'bearer', expires_in: 900 }),
      'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS),
      'GET /api/v1/transactions': () => jsonResponse(TXS),
    })
    renderApp('/login')
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Identifiant'), 'demo01')
    await user.type(screen.getByLabelText('Mot de passe'), 'secret')
    await user.click(screen.getByRole('button', { name: 'Se connecter' }))

    await waitFor(() => expect(screen.getByTestId('balance')).toHaveTextContent(/1\s?250,50/))
    expect(tokenStore.get()).toBe(jwt)
    expect(screen.getByText('Bonjour demo01')).toBeInTheDocument()
    expect(await screen.findByText(/Loyer/)).toBeInTheDocument()
    expect(screen.getByText(/Session \d+:\d{2}/)).toBeInTheDocument()
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

  it('champs vides : erreur client sans appel réseau ; raccourci de démo = identifiant seul', async () => {
    const f = stubFetch({})
    renderApp('/login')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Se connecter' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Renseignez votre identifiant et votre mot de passe.')
    expect(f).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'demo02' }))
    expect(screen.getByLabelText('Identifiant')).toHaveValue('demo02')
    expect(screen.getByLabelText('Mot de passe')).toHaveValue('')
  })

  it('401 sur une page protégée => retour au login, jeton effacé, message d’expiration', async () => {
    loginAsStored()
    const expired = () => jsonResponse({ error: { code: 'token_expired', message: 'x' } }, 401)
    stubFetch({ 'GET /api/v1/accounts': expired, 'GET /api/v1/transactions': expired })
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'Connexion' })).toBeInTheDocument()
    expect(screen.getByText(/Votre session a expiré/)).toBeInTheDocument()
    expect(tokenStore.get()).toBeNull()
  })

  it('déconnexion manuelle', async () => {
    loginAsStored()
    stubFetch({ 'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS), 'GET /api/v1/transactions': () => jsonResponse([]) })
    renderApp('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Se déconnecter' }))
    expect(screen.getByRole('heading', { name: 'Connexion' })).toBeInTheDocument()
    expect(screen.getByText('Vous êtes déconnecté.')).toBeInTheDocument()
    expect(tokenStore.get()).toBeNull()
  })
})

describe('Front - espace client', () => {
  it('accueil : état de chargement puis erreur avec réessai', async () => {
    loginAsStored()
    let calls = 0
    stubFetch({
      'GET /api/v1/accounts': () =>
        ++calls === 1 ? jsonResponse({ error: { code: 'db_error', message: 'DB down', request_id: 'rid-9' } }, 503) : jsonResponse(ACCOUNTS),
      'GET /api/v1/transactions': () => jsonResponse([]),
    })
    renderApp('/')
    expect(screen.getByRole('status', { name: 'Chargement des comptes…' })).toBeInTheDocument()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('DB down')
    expect(alert).toHaveTextContent('rid-9')
    await userEvent.click(within(alert).getByRole('button', { name: 'Réessayer' }))
    await waitFor(() => expect(screen.getByTestId('balance')).toHaveTextContent(/1\s?250,50/))
    expect(screen.getByText('Aucune opération pour le moment.')).toBeInTheDocument()
  })

  it('comptes : « Virer depuis ce compte » pré-sélectionne le compte à débiter', async () => {
    loginAsStored()
    stubFetch({ 'GET /api/v1/accounts': () => jsonResponse(TWO_ACCOUNTS), 'GET /api/v1/transactions': () => jsonResponse([]) })
    renderApp('/accounts')
    const card = await screen.findByRole('article', { name: 'Compte #2' })
    expect(card).toHaveTextContent('FR76 0000 0002')
    await userEvent.click(within(card).getByRole('button', { name: 'Virer depuis ce compte' }))
    expect(await screen.findByRole('button', { name: 'Débiter le compte #2' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Débiter le compte #1' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('historique : statuts, filtres avec compteurs, libellé local', async () => {
    loginAsStored()
    labelStore.save('2', 'Achat refusé')
    stubFetch({ 'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS), 'GET /api/v1/transactions': () => jsonResponse(TXS) })
    renderApp('/history')
    const table = await screen.findByRole('table', { name: 'Opérations' })
    expect(within(table).getByText('Effectué')).toBeInTheDocument()
    expect(within(table).getByText('Rejeté')).toBeInTheDocument()
    expect(within(table).getByText('Achat refusé')).toBeInTheDocument()
    // Le plus récent d'abord.
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('#98')

    await userEvent.click(screen.getByRole('button', { name: /Rejetées\s*1/ }))
    expect(within(table).queryByText('Effectué')).not.toBeInTheDocument()
    expect(within(table).getByText('Rejeté')).toBeInTheDocument()
  })
})

describe('Front - virement', () => {
  it('validation client puis POST /api/v1/transactions, libellé conservé localement', async () => {
    loginAsStored()
    const fetchMock = stubFetch({
      'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS),
      'GET /api/v1/transactions': () => jsonResponse([]),
      'POST /api/v1/transactions': () =>
        jsonResponse({ id: 77, src_account: 1, dst_account: 77, amount_cents: 2550, status: 'created', created_at: '2026-10-21T10:00:00Z' }, 201),
    })
    renderApp('/transfer')
    const user = userEvent.setup()
    await screen.findByRole('group', { name: 'Compte à débiter' })

    await user.click(screen.getByRole('button', { name: 'Envoyer le virement' }))
    expect(screen.getByText('Indiquez le compte bénéficiaire.')).toBeInTheDocument()
    expect(screen.getByText('Indiquez un montant.')).toBeInTheDocument()
    expect(posts(fetchMock)).toHaveLength(0)

    await user.type(screen.getByLabelText('Compte bénéficiaire'), '77')
    await user.type(screen.getByLabelText('Montant'), '25,50')
    await user.type(screen.getByLabelText(/Libellé/), 'Cadeau')
    expect(within(screen.getByRole('complementary', { name: 'Récapitulatif' })).getByText(/1\s?225,00/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Envoyer 25,50/ }))

    expect(await screen.findByRole('status')).toHaveTextContent(/Virement accepté/)
    const [post] = posts(fetchMock)
    expect(JSON.parse((post![1] as RequestInit).body as string)).toEqual({ src_account: 1, dst_account: 77, amount_cents: 2550 })
    expect(labelStore.all()).toEqual({ '77': 'Cadeau' })
  })

  it('montant supérieur au solde : bloqué côté client', async () => {
    loginAsStored()
    const fetchMock = stubFetch({ 'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS), 'GET /api/v1/transactions': () => jsonResponse([]) })
    renderApp('/transfer')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Compte bénéficiaire'), '77')
    await user.type(screen.getByLabelText('Montant'), '5000')
    await user.click(screen.getByRole('button', { name: /Envoyer/ }))
    expect(screen.getByText('Montant supérieur au solde disponible.')).toBeInTheDocument()
    expect(posts(fetchMock)).toHaveLength(0)
  })

  it('refus serveur insufficient_funds (409) : carte « Virement refusé » avec le code', async () => {
    loginAsStored()
    stubFetch({
      'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS),
      'GET /api/v1/transactions': () => jsonResponse([]),
      'POST /api/v1/transactions': () =>
        jsonResponse({ error: { code: 'insufficient_funds', message: 'Insufficient funds', request_id: 'rid-1' } }, 409),
    })
    renderApp('/transfer')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Compte bénéficiaire'), '77')
    await user.type(screen.getByLabelText('Montant'), '10')
    await user.click(screen.getByRole('button', { name: /Envoyer/ }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Virement refusé')
    expect(alert).toHaveTextContent('Solde insuffisant pour ce virement.')
    expect(alert).toHaveTextContent('rid-1')
  })

  it('autre erreur serveur : bandeau sous le formulaire, saisie conservée', async () => {
    loginAsStored()
    stubFetch({
      'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS),
      'GET /api/v1/transactions': () => jsonResponse([]),
      'POST /api/v1/transactions': () => jsonResponse({ error: { code: 'db_error', message: 'Service indisponible' } }, 503),
    })
    renderApp('/transfer')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Compte bénéficiaire'), '77')
    await user.type(screen.getByLabelText('Montant'), '10')
    await user.click(screen.getByRole('button', { name: /Envoyer/ }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('code=db_error'))
    expect(screen.getByLabelText('Compte bénéficiaire')).toHaveValue('77')
  })
})
