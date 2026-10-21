import { act } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { App } from './App'
import { AuthProvider } from './components/AuthProvider'
import { fakeJwt, jsonResponse, setViewport, stubFetch } from './test/helpers'
import { tokenStore } from './api/tokenStore'
import { labelStore } from './lib/labels'

// Fixtures au format réel de payment-api : centimes entiers, ids numériques, src_/dst_account.
const ACCOUNTS = [{ id: 1, iban_fake: 'FR76 0000 0001', balance_cents: 125050, currency: 'EUR' }]
const TWO_ACCOUNTS = [...ACCOUNTS, { id: 2, iban_fake: 'FR76 0000 0002', balance_cents: 5000, currency: 'EUR' }]
const TXS = [
  { id: 1, src_account: 1, dst_account: 99, amount_cents: 2000, status: 'created', created_at: '2026-10-21T09:14:33Z', request_id: 'req-abc' },
  { id: 2, src_account: 1, dst_account: 98, amount_cents: 999900, status: 'rejected', created_at: '2026-10-21T09:15:00Z' },
]
const CREATED = { id: 77, src_account: 1, dst_account: 77, amount_cents: 2550, status: 'created', created_at: '2026-10-21T10:00:00Z', request_id: 'req-77' }

function renderApp(path = '/', { desktop = true } = {}) {
  setViewport(desktop)
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
const bodyOf = (f: ReturnType<typeof stubFetch>) => JSON.parse((posts(f)[0]![1] as RequestInit).body as string)

describe('Front - connexion', () => {
  it('redirige vers /login sans jeton, avec un message de garde', () => {
    renderApp('/history')
    expect(screen.getByRole('heading', { name: 'Connexion' })).toBeInTheDocument()
    expect(screen.getByText('Connectez-vous pour accéder à cette page.')).toBeInTheDocument()
  })

  it('login réussi : stocke le JWT, accueil « Bonjour » + solde total + opérations récentes', async () => {
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
    expect(screen.getByRole('heading', { level: 1, name: 'demo01' })).toBeInTheDocument()
    expect(screen.getByText('Bonjour')).toBeInTheDocument()
    const recent = screen.getByRole('region', { name: 'Opérations récentes' })
    expect(await within(recent).findByText('Compte n°99 · ' + new Date(TXS[0]!.created_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }))).toBeInTheDocument()
    expect(within(recent).getByText('Refusé')).toBeInTheDocument()
    expect(screen.getByText(/^\d{2}:\d{2}$/)).toBeInTheDocument() // session restante (barre latérale)
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

  it('déconnexion depuis le Profil, avec confirmation', async () => {
    loginAsStored()
    stubFetch({ 'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS), 'GET /api/v1/transactions': () => jsonResponse([]) })
    renderApp('/profile', { desktop: false })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Se déconnecter' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Se déconnecter ?' })
    await user.click(within(dialog).getByRole('button', { name: 'Se déconnecter' }))
    expect(screen.getByRole('heading', { name: 'Connexion' })).toBeInTheDocument()
    expect(screen.getByText('Vous êtes déconnecté.')).toBeInTheDocument()
    expect(tokenStore.get()).toBeNull()
  })
})

describe('Front - shell responsive', () => {
  it('desktop : barre latérale (navigation + services), pas de barre d’onglets', async () => {
    loginAsStored()
    stubFetch({ 'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS), 'GET /api/v1/transactions': () => jsonResponse([]) })
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Navigation principale' })
    expect(within(nav).getByRole('button', { name: 'Accueil' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'RIB' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Onglets' })).not.toBeInTheDocument()
  })

  it('mobile : barre d’onglets, navigation vers Historique', async () => {
    loginAsStored()
    stubFetch({ 'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS), 'GET /api/v1/transactions': () => jsonResponse(TXS) })
    renderApp('/', { desktop: false })
    const tabs = await screen.findByRole('navigation', { name: 'Onglets' })
    expect(screen.queryByRole('navigation', { name: 'Navigation principale' })).not.toBeInTheDocument()
    await userEvent.click(within(tabs).getByRole('button', { name: 'Historique' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Historique' })).toBeInTheDocument()
    expect(within(tabs).getByRole('button', { name: 'Historique' })).toHaveAttribute('aria-current', 'page')
  })
})

describe('Front - espace client', () => {
  it('accueil : chargement puis erreur avec référence et réessai', async () => {
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

  it('bandeau d’état : « Service perturbé » sur 5xx puis « Service rétabli » à la reprise, sans action', async () => {
    loginAsStored()
    let calls = 0
    stubFetch({
      'GET /api/v1/accounts': () => (++calls === 1 ? jsonResponse({ error: { code: 'upstream', message: 'x' } }, 503) : jsonResponse(ACCOUNTS)),
      'GET /api/v1/transactions': () => jsonResponse([]),
    })
    renderApp('/')
    expect(await screen.findByText('Service perturbé — reprise automatique en cours')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Réessayer' }))
    expect(await screen.findByText('Service rétabli')).toBeInTheDocument()
    expect(screen.queryByText(/Service perturbé/)).not.toBeInTheDocument()
  })

  it('incident pendant que l’utilisateur ne fait rien : le rafraîchissement périodique affiche le bandeau', async () => {
    loginAsStored()
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    let down = false
    const fail = () => jsonResponse({ error: { code: 'upstream', message: 'x' } }, 503)
    const degraded = () => jsonResponse({ status: 'degraded', checked_at: '2026-10-21T10:00:00Z' }, 503)
    let dbDown = false
    const f = stubFetch({
      'GET /api/v1/accounts': () => (down ? fail() : jsonResponse(ACCOUNTS)),
      'GET /api/v1/transactions': () => (down ? fail() : jsonResponse(TXS)),
      'GET /api/v1/status': () => (dbDown ? degraded() : jsonResponse({ status: 'ok', checked_at: '2026-10-21T10:00:05Z' })),
    })
    const statusCalls = () => f.mock.calls.filter(([u]) => String(u).endsWith('/api/v1/status'))
    try {
      renderApp('/')
      await screen.findByTestId('balance')
      expect(statusCalls()).toHaveLength(0) // pas de sonde tant que tout va bien
      down = dbDown = true
      act(() => vi.advanceTimersByTime(15_000))
      expect(await screen.findByText('Service perturbé — reprise automatique en cours')).toBeInTheDocument()
      // Les données déjà affichées restent visibles pendant l'incident.
      expect(screen.getByTestId('balance')).toHaveTextContent(/1\s?250,50/)
      act(() => vi.advanceTimersByTime(5_000)) // sonde : encore « degraded » (503)
      await waitFor(() => expect(statusCalls()).toHaveLength(1))
      expect(screen.getByText('Service perturbé — reprise automatique en cours')).toBeInTheDocument()
      const [, init] = statusCalls()[0] as unknown as [string, RequestInit]
      expect((init.headers as Record<string, string>).Authorization).toBeUndefined() // route publique
      dbDown = false // BDD revenue, mais les routes métier échouent encore : pas de faux « rétabli »
      act(() => vi.advanceTimersByTime(5_000))
      await waitFor(() => expect(statusCalls()).toHaveLength(2))
      await waitFor(() => expect(f.mock.calls.filter(([u]) => String(u).endsWith('/api/v1/accounts')).length).toBeGreaterThan(1))
      expect(screen.getByText('Service perturbé — reprise automatique en cours')).toBeInTheDocument()
      down = false
      act(() => vi.advanceTimersByTime(5_000)) // sonde ok puis /accounts ok : reprise confirmée
      expect(await screen.findByText('Service rétabli')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('historique : groupé par jour, rejet visible, libellé local, filtre Refusés, détail avec référence', async () => {
    loginAsStored()
    labelStore.save('2', 'Achat refusé')
    stubFetch({ 'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS), 'GET /api/v1/transactions': () => jsonResponse(TXS) })
    renderApp('/history')
    const user = userEvent.setup()
    expect(await screen.findByText('2 opérations')).toBeInTheDocument()
    expect(screen.getByText('Achat refusé')).toBeInTheDocument()
    // Le plus récent d'abord.
    const rows = screen.getAllByRole('button', { name: /Compte n°9\d/ })
    expect(rows[0]).toHaveTextContent('Achat refusé')

    await user.click(screen.getByRole('button', { name: 'Refusés' }))
    expect(screen.getByText('1 opération')).toBeInTheDocument()
    expect(screen.queryByText('Virement émis')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Tous', pressed: false }))
    await user.click(screen.getByRole('button', { name: /Virement émis/ }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Détail de l’opération' })).toBeInTheDocument()
    expect(screen.getByText('req-abc')).toBeInTheDocument()
    expect(screen.getByTestId('tx-amount')).toHaveTextContent(/−\s?20,00/)
  })

  it('historique mobile : feuille de filtres et pastille de filtre actif', async () => {
    loginAsStored()
    stubFetch({ 'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS), 'GET /api/v1/transactions': () => jsonResponse(TXS) })
    renderApp('/history', { desktop: false })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Filtres' }))
    const sheet = screen.getByRole('dialog', { name: 'Filtres' })
    await user.click(within(sheet).getByRole('button', { name: 'Refusés' }))
    await user.click(within(sheet).getByRole('button', { name: 'Afficher 1 opération' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Filtres, 1 actifs' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retirer le filtre Refusés' }))
    expect(screen.getByText('2 opérations')).toBeInTheDocument()
  })

  it('RIB : choix du compte depuis la carte de l’accueil', async () => {
    loginAsStored()
    stubFetch({ 'GET /api/v1/accounts': () => jsonResponse(TWO_ACCOUNTS), 'GET /api/v1/transactions': () => jsonResponse([]) })
    renderApp('/')
    await userEvent.click(await screen.findByRole('button', { name: /^Compte n°2, solde/ }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Relevé d’identité bancaire' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'RIB du Compte n°2' })).toHaveTextContent('FR76 0000 0002')
    expect(screen.getByRole('button', { name: 'Compte n°2' })).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('Front - envoi (desktop)', () => {
  const routes = (post: () => Response) => ({
    'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS),
    'GET /api/v1/transactions': () => jsonResponse([]),
    'POST /api/v1/transactions': post,
  })

  async function fillDesktop(amount: string, label = '') {
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Rechercher un destinataire par nom ou numéro de compte'), '77')
    await user.click(screen.getByRole('button', { name: 'Compte n°77' }))
    const input = screen.getByLabelText('Montant en euros')
    await user.clear(input)
    await user.type(input, amount)
    if (label) await user.type(screen.getByLabelText(/Libellé/), label)
    return user
  }

  it('validation, récapitulatif puis POST /api/v1/transactions ; libellé conservé localement', async () => {
    loginAsStored()
    const f = stubFetch(routes(() => jsonResponse(CREATED, 201)))
    renderApp('/send')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /^Envoyer 50,00/ }))
    expect(screen.getByRole('alert')).toHaveTextContent('Choisissez un destinataire.')

    await fillDesktop('25,50', 'Cadeau')
    await user.click(screen.getByRole('button', { name: /^Envoyer 25,50/ }))
    expect(screen.getByText('Récapitulatif')).toBeInTheDocument()
    expect(posts(f)).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: 'Confirmer l’envoi' }))

    expect(await screen.findByRole('heading', { name: 'Virement envoyé' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copier la référence' })).toHaveTextContent('req-77')
    expect(bodyOf(f)).toEqual({ src_account: 1, dst_account: 77, amount_cents: 2550 })
    expect(labelStore.all()).toEqual({ '77': 'Cadeau' })
  })

  it('montant supérieur au solde : bloqué côté client', async () => {
    loginAsStored()
    const f = stubFetch(routes(() => jsonResponse(CREATED, 201)))
    renderApp('/send')
    const user = await fillDesktop('5000')
    await user.click(screen.getByRole('button', { name: /^Envoyer 5\s?000,00/ }))
    expect(screen.getByRole('alert')).toHaveTextContent('Montant supérieur au solde disponible.')
    expect(posts(f)).toHaveLength(0)
  })

  it('refus serveur insufficient_funds (409) : « Virement refusé — solde insuffisant »', async () => {
    loginAsStored()
    stubFetch(routes(() => jsonResponse({ error: { code: 'insufficient_funds', message: 'Insufficient funds', request_id: 'rid-1' } }, 409)))
    renderApp('/send')
    const user = await fillDesktop('10')
    await user.click(screen.getByRole('button', { name: /^Envoyer 10,00/ }))
    await user.click(screen.getByRole('button', { name: 'Confirmer l’envoi' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Virement refusé — solde insuffisant')
    expect(alert).toHaveTextContent('rid-1')
  })

  it('erreur technique (503) : « n’a pas pu être transmis » puis Réessayer renvoie le virement', async () => {
    loginAsStored()
    let n = 0
    const f = stubFetch(routes(() => (++n === 1 ? jsonResponse({ error: { code: 'db_error', message: 'Service indisponible' } }, 503) : jsonResponse(CREATED, 201))))
    renderApp('/send')
    const user = await fillDesktop('10')
    await user.click(screen.getByRole('button', { name: /^Envoyer 10,00/ }))
    await user.click(screen.getByRole('button', { name: 'Confirmer l’envoi' }))
    expect(await screen.findByRole('heading', { name: 'Le virement n’a pas pu être transmis' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))
    expect(await screen.findByRole('heading', { name: 'Virement envoyé' })).toBeInTheDocument()
    expect(posts(f)).toHaveLength(2)
  })
})

describe('Front - envoi : statut inconnu', () => {
  it('coupure réseau pendant l’envoi : pas de « Réessayer » (risque de double débit), renvoi vers l’historique', async () => {
    loginAsStored()
    const f = stubFetch({
      'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS),
      'GET /api/v1/transactions': () => jsonResponse([]),
      'POST /api/v1/transactions': () => {
        throw new TypeError('Failed to fetch')
      },
    })
    renderApp('/send')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Rechercher un destinataire par nom ou numéro de compte'), '77')
    await user.click(screen.getByRole('button', { name: 'Compte n°77' }))
    await user.click(screen.getByRole('button', { name: /^Envoyer 50,00/ }))
    await user.click(screen.getByRole('button', { name: 'Confirmer l’envoi' }))
    expect(await screen.findByRole('heading', { name: 'Statut du virement inconnu' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Réessayer' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Voir l’historique' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Historique' })).toBeInTheDocument()
    expect(posts(f)).toHaveLength(1)
  })
})

describe('Front - envoi (mobile, assistant 4 étapes)', () => {
  it('destinataire → montant → détails → glisser pour envoyer (clavier)', async () => {
    loginAsStored()
    const f = stubFetch({
      'GET /api/v1/accounts': () => jsonResponse(TWO_ACCOUNTS),
      'GET /api/v1/transactions': () => jsonResponse(TXS),
      'POST /api/v1/transactions': () => jsonResponse({ ...CREATED, dst_account: 99 }, 201),
    })
    renderApp('/send', { desktop: false })
    const user = userEvent.setup()
    expect(await screen.findByText('Étape 1 sur 4')).toBeInTheDocument()
    // Mes autres comptes puis les comptes déjà crédités.
    const list = screen.getByRole('region', { name: 'Destinataires' })
    expect(within(list).getAllByRole('button').map((b) => b.textContent)).toEqual([
      expect.stringContaining('Compte n°2'),
      expect.stringContaining('Compte n°98'),
      expect.stringContaining('Compte n°99'),
    ])
    await user.click(within(list).getByRole('button', { name: /Compte n°99/ }))

    expect(screen.getByText('Étape 2 sur 4')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '100 €' }))
    await user.click(screen.getByRole('button', { name: /Continuer/ }))
    expect(screen.getByText('Étape 3 sur 4')).toBeInTheDocument()
    // Retour de l'en-tête = étape précédente.
    await user.click(screen.getByRole('button', { name: 'Retour' }))
    expect(screen.getByText('Étape 2 sur 4')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Continuer/ }))
    await user.click(screen.getByRole('button', { name: /Vérifier le virement/ }))

    expect(screen.getByText('Étape 4 sur 4')).toBeInTheDocument()
    expect(screen.getByText('Vous envoyez à Compte n°99')).toBeInTheDocument()
    screen.getByRole('button', { name: /^Envoyer 100,00\s€ à Compte n°99/ }).focus()
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('heading', { name: 'Virement envoyé' }, { timeout: 3000 })).toBeInTheDocument()
    expect(bodyOf(f)).toEqual({ src_account: 1, dst_account: 99, amount_cents: 10000 })
  })

  it('depuis l’accueil, un destinataire récent ouvre directement l’étape Montant', async () => {
    loginAsStored()
    stubFetch({ 'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS), 'GET /api/v1/transactions': () => jsonResponse(TXS) })
    renderApp('/', { desktop: false })
    await userEvent.click(await screen.findByRole('button', { name: 'Envoyer à Compte n°99' }))
    expect(await screen.findByText('Étape 2 sur 4')).toBeInTheDocument()
    expect(screen.getByText('Compte n°99')).toBeInTheDocument()
  })
})

describe('Front - bénéficiaires (#43)', () => {
  const LEA = { id: 5, display_name: 'Léa Martin', account_id: 42, iban_fake: 'FR76 0000 0000 9001 0000 0000 000', created_at: '2026-10-21T10:00:00Z' }
  const HUGO = { id: 6, display_name: 'Hugo Bernard', account_id: 43, iban_fake: 'FR76 0000 0000 9002 0000 0000 000', created_at: '2026-10-21T10:00:00Z' }

  it('accueil : « Envoyer à » propose les bénéficiaires par leur nom, puis Envoyer pré-remplit le destinataire', async () => {
    loginAsStored()
    stubFetch({
      'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS),
      'GET /api/v1/transactions': () => jsonResponse([]),
      'GET /api/v1/beneficiaries': () => jsonResponse([LEA]),
    })
    renderApp('/', { desktop: false })
    await userEvent.click(await screen.findByRole('button', { name: 'Envoyer à Léa Martin' }))
    expect(await screen.findByText('Étape 2 sur 4')).toBeInTheDocument()
    expect(screen.getByText('Léa Martin')).toBeInTheDocument()
  })

  it('liste + recherche, ajout refusé (IBAN inconnu) puis accepté, suppression confirmée', async () => {
    loginAsStored()
    let list = [LEA]
    const f = stubFetch({
      'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS),
      'GET /api/v1/transactions': () => jsonResponse([]),
      'GET /api/v1/beneficiaries': () => jsonResponse(list),
      'POST /api/v1/beneficiaries': (init) => {
        const body = JSON.parse(init!.body as string)
        if (body.iban_fake !== HUGO.iban_fake) return jsonResponse({ error: { code: 'account_not_found', message: 'x' } }, 404)
        list = [LEA, HUGO]
        return jsonResponse(HUGO, 201)
      },
      'DELETE /api/v1/beneficiaries/5': () => {
        list = [HUGO]
        return new Response(null, { status: 204 })
      },
    })
    renderApp('/beneficiaries')
    const user = userEvent.setup()
    const rows = await screen.findByRole('list', { name: 'Bénéficiaires' })
    expect(within(rows).getByText('Léa Martin')).toBeInTheDocument()
    await user.type(screen.getByRole('searchbox', { name: 'Rechercher un bénéficiaire' }), 'zzz')
    expect(screen.getByText('Aucun résultat')).toBeInTheDocument()
    await user.clear(screen.getByRole('searchbox', { name: 'Rechercher un bénéficiaire' }))

    await user.click(screen.getByRole('button', { name: 'Ajouter' }))
    const form = screen.getByRole('form', { name: 'Nouveau bénéficiaire' })
    await user.type(within(form).getByLabelText('Nom'), 'Hugo Bernard')
    await user.type(within(form).getByLabelText('IBAN'), 'FR76 NOPE')
    await user.click(within(form).getByRole('button', { name: 'Enregistrer le bénéficiaire' }))
    expect(await within(form).findByText('Aucun compte ne correspond à cet IBAN.')).toBeInTheDocument()
    await user.clear(within(form).getByLabelText('IBAN'))
    await user.type(within(form).getByLabelText('IBAN'), HUGO.iban_fake)
    await user.click(within(form).getByRole('button', { name: 'Enregistrer le bénéficiaire' }))
    expect(await screen.findByText('Hugo Bernard')).toBeInTheDocument()
    expect(JSON.parse((posts(f).at(-1)![1] as RequestInit).body as string)).toEqual({ display_name: 'Hugo Bernard', iban_fake: HUGO.iban_fake })

    await user.click(screen.getByRole('button', { name: 'Supprimer Léa Martin' }))
    const dlg = screen.getByRole('alertdialog')
    await user.click(within(dlg).getByRole('button', { name: 'Supprimer' }))
    await waitFor(() => expect(screen.queryByText('Léa Martin')).not.toBeInTheDocument())
    expect(f.mock.calls.some(([u, i]) => String(u).endsWith('/api/v1/beneficiaries/5') && (i as RequestInit).method === 'DELETE')).toBe(true)
  })

  it('annuler la suppression ne supprime rien', async () => {
    loginAsStored()
    const f = stubFetch({
      'GET /api/v1/accounts': () => jsonResponse(ACCOUNTS),
      'GET /api/v1/transactions': () => jsonResponse([]),
      'GET /api/v1/beneficiaries': () => jsonResponse([LEA]),
    })
    renderApp('/beneficiaries')
    await userEvent.click(await screen.findByRole('button', { name: 'Supprimer Léa Martin' }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: /Annuler/ }))
    expect(screen.getByText('Léa Martin')).toBeInTheDocument()
    expect(f.mock.calls.some(([, i]) => (i as RequestInit | undefined)?.method === 'DELETE')).toBe(false)
  })
})
