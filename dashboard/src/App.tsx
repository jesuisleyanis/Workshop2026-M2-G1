import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AssistantTab } from './components/AssistantTab'
import { ActionsPanel, EvidencePanel, PlaybooksPanel, SignalsPanel } from './components/IncidentDetails'
import { IncidentTimeline } from './components/IncidentTimeline'
import { MetricsCards, ScoreCard, VerificationCard } from './components/MetricsCards'
import { PhaseBanner } from './components/PhaseBanner'
import { ScoreChart } from './components/ScoreChart'
import { ServicesGrid } from './components/ServicesGrid'
import { Sidebar } from './components/Sidebar'
import { ASSISTANT_URL, GRAFANA_BASE, LIVE_TRIGGERS, STREAM_SOURCE, STREAM_URL, TRIGGER_URL, type StreamSource } from './config'
import { useDashboard } from './hooks/useDashboard'
import { useNow } from './hooks/useNow'
import { defaultFactory, type EventSourceFactory } from './hooks/useRemediationStream'
import { SimulatedEventSource, type SimulatedType } from './lib/simulator'
import { currentThreshold, latestIncident, scoredServices } from './lib/state'

type Tab = 'supervision' | 'assistant'
const TABS: [Tab, string][] = [
  ['supervision', 'Supervision'],
  ['assistant', 'Assistant'],
]

interface Props {
  streamUrl?: string
  assistantUrl?: string
  /** Injection pour les tests. */
  eventSourceFactory?: EventSourceFactory
  source?: StreamSource
  liveTriggers?: boolean
  grafanaBase?: string
}

/** Choisit la source (flux réel / simulation) ; la console est remontée à chaque bascule. */
export function App({ streamUrl = STREAM_URL, assistantUrl = ASSISTANT_URL, eventSourceFactory, source = STREAM_SOURCE, liveTriggers = LIVE_TRIGGERS, grafanaBase = GRAFANA_BASE }: Props) {
  const [simulated, setSimulated] = useState(source === 'simulation')
  const [fallback, setFallback] = useState(false)

  const onNeverOpened = useCallback(() => {
    setFallback(true)
    setSimulated(true)
  }, [])

  return (
    <Console
      key={simulated ? 'sim' : 'live'}
      streamUrl={streamUrl}
      eventSourceFactory={eventSourceFactory}
      simulated={simulated}
      fallback={fallback}
      // Bascule automatique une seule fois : « Réessayer le flux réel » reste ensuite en réel.
      onNeverOpened={source === 'auto' && !fallback ? onNeverOpened : undefined}
      onToggleSource={() => setSimulated((s) => !s)}
      liveTriggers={liveTriggers}
      grafanaBase={grafanaBase}
      assistantUrl={assistantUrl}
    />
  )
}

interface ConsoleProps {
  streamUrl: string
  assistantUrl: string
  eventSourceFactory?: EventSourceFactory
  simulated: boolean
  fallback: boolean
  onNeverOpened?: () => void
  onToggleSource: () => void
  liveTriggers: boolean
  grafanaBase: string
}

function Console({ streamUrl, assistantUrl, eventSourceFactory, simulated, fallback, onNeverOpened, onToggleSource, liveTriggers, grafanaBase }: ConsoleProps) {
  const [tab, setTab] = useState<Tab>('supervision')
  // L'iframe n'est montée qu'au premier affichage de l'onglet, puis conservée.
  const [assistantMounted, setAssistantMounted] = useState(false)
  const select = (t: Tab) => {
    setTab(t)
    if (t === 'assistant') setAssistantMounted(true)
  }
  const simRef = useRef<SimulatedEventSource | null>(null)
  const factory = useMemo<EventSourceFactory>(
    () => (simulated ? () => (simRef.current = new SimulatedEventSource()) : (eventSourceFactory ?? defaultFactory)),
    [simulated, eventSourceFactory],
  )
  const { state, phase, reset } = useDashboard(simulated ? 'simulation://local' : streamUrl, factory)
  const now = useNow(250)
  const incident = latestIncident(state)

  // Flux réel jamais ouvert (moteur injoignable) => simulation, si le mode `auto` l'autorise.
  const everOpen = useRef(false)
  useEffect(() => {
    if (state.connection === 'open') everOpen.current = true
    else if ((state.connection === 'reconnecting' || state.connection === 'closed') && !everOpen.current) onNeverOpened?.()
  }, [state.connection, onNeverOpened])

  // Service suivi : choix manuel, sinon le service de l'incident, sinon le premier scoré.
  // Un nouvel incident rend la main au suivi automatique.
  const services = scoredServices(state.history)
  const [picked, setPicked] = useState<string | null>(null)
  const [seenIncident, setSeenIncident] = useState(incident?.id)
  if (incident?.id !== seenIncident) {
    setSeenIncident(incident?.id)
    setPicked(null)
  }
  const focus = picked ?? (incident && services.includes(incident.service) ? incident.service : (services[0] ?? null))
  const focusScore = state.history.findLast((h) => h.service === focus) ?? state.score

  const [flash, setFlash] = useState<string | null>(null)
  const flashTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const toast = (m: string) => {
    clearTimeout(flashTimer.current)
    setFlash(m)
    flashTimer.current = setTimeout(() => setFlash(null), 3500)
  }
  useEffect(() => () => clearTimeout(flashTimer.current), [])

  const trigger = async (type: SimulatedType) => {
    if (simulated) {
      toast(simRef.current?.trigger(type) ? `Incident ${type} lancé (simulation)` : 'Un incident simulé est déjà en cours')
      return
    }
    try {
      const r = await fetch(`${TRIGGER_URL}?type=${encodeURIComponent(type)}`)
      const j = (await r.json().catch(() => ({}))) as { started?: boolean }
      toast(j.started ? `Incident ${type} démarré` : `Déclenchement refusé (HTTP ${r.status})`)
    } catch {
      toast('Déclencheur injoignable')
    }
  }

  return (
    <div className="grid min-h-screen bg-bg lg:grid-cols-[236px_minmax(0,1fr)]">
      <Sidebar
        connection={state.connection}
        now={now}
        streamUrl={streamUrl}
        simulated={simulated}
        fallback={fallback}
        onToggleSource={onToggleSource}
        onTrigger={simulated || liveTriggers ? trigger : null}
      />

      <main className="flex min-w-0 flex-col gap-[22px] px-[clamp(16px,2.5vw,32px)] pt-7 pb-10">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-1.5">
            <h1 className="text-[30px] font-medium tracking-[-0.02em]">Supervision temps réel</h1>
            <span className="text-[13px] text-mute-2">Banque Résilience · plateforme de paiement fictive — exercice Blue Team, données factices</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {state.rejected > 0 && (
              <span className="rounded-lg bg-warn/10 px-2.5 py-1.5 text-xs text-warn" title="Messages du flux rejetés (non conformes au contrat)">
                {state.rejected} message{state.rejected > 1 ? 's' : ''} rejeté{state.rejected > 1 ? 's' : ''}
              </span>
            )}
            {flash && (
              <span role="status" className="rounded-lg bg-accent/10 px-2.5 py-1.5 text-xs text-accent-2">
                {flash}
              </span>
            )}
            <button
              type="button"
              onClick={reset}
              title="Écarte l'incident affiché et revient à AVANT (reprise de clip)"
              className="h-[34px] cursor-pointer rounded-full border border-[#333339] px-3.5 text-[13px] hover:bg-[#1b1b1e]"
            >
              Réinitialiser la vue
            </button>
          </div>
        </header>

        <div role="tablist" aria-label="Vues" className="flex gap-2 border-b border-edge">
          {TABS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`tab-${id}`}
              aria-controls={`panel-${id}`}
              aria-selected={tab === id}
              onClick={() => select(id)}
              className={`-mb-px cursor-pointer border-b-2 px-4 py-2 text-[13px] font-medium ${
                tab === id ? 'border-accent text-accent-2' : 'border-transparent text-mute hover:text-fg-2'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* hidden (pas de rendu conditionnel) : la supervision reste montée, le flux SSE n'est pas coupé. */}
        <div role="tabpanel" id="panel-supervision" aria-labelledby="tab-supervision" hidden={tab !== 'supervision'} className="flex flex-col gap-[22px]">
        <PhaseBanner phase={phase} incident={incident} />

        <section aria-label="Indicateurs" className="grid grid-cols-[repeat(auto-fit,minmax(210px,1fr))] gap-3.5">
          <ScoreCard score={focusScore} history={state.history} />
          <MetricsCards incident={incident} now={now} />
          <VerificationCard verify={state.lastVerification} now={now} />
        </section>

        <div className="flex flex-wrap items-start gap-[18px]">
          <div className="flex min-w-0 flex-[1_1_560px] flex-col gap-[18px]">
            <ScoreChart
              history={state.history}
              services={services}
              focus={focus}
              onFocus={setPicked}
              threshold={currentThreshold(state)}
              incident={incident}
              now={now}
            />
            <IncidentTimeline incident={incident} now={now} />
            <ActionsPanel incident={incident} />
          </div>
          <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-[18px]">
            <ServicesGrid services={state.services} />
            <SignalsPanel incident={incident} />
            <PlaybooksPanel incident={incident} />
            <EvidencePanel incident={incident} grafanaBase={grafanaBase} />
          </div>
        </div>
        </div>

        <div role="tabpanel" id="panel-assistant" aria-labelledby="tab-assistant" hidden={tab !== 'assistant'}>
          {assistantMounted && <AssistantTab url={assistantUrl} />}
        </div>
      </main>
    </div>
  )
}
