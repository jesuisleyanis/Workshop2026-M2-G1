import { GrafanaLinks } from './components/GrafanaLinks'
import { Header } from './components/Header'
import { IncidentTimeline } from './components/IncidentTimeline'
import { MetricsCards } from './components/MetricsCards'
import { PhaseBanner } from './components/PhaseBanner'
import { ScoreGauge } from './components/ScoreGauge'
import { ServicesGrid } from './components/ServicesGrid'
import { VerificationCard } from './components/VerificationCard'
import { STREAM_URL } from './config'
import { useDashboard } from './hooks/useDashboard'
import { useNow } from './hooks/useNow'
import type { EventSourceFactory } from './hooks/useRemediationStream'
import { latestIncident } from './lib/state'

interface Props {
  streamUrl?: string
  /** Injection pour les tests. */
  eventSourceFactory?: EventSourceFactory
}

export function App({ streamUrl = STREAM_URL, eventSourceFactory }: Props) {
  const { state, phase, reset } = useDashboard(streamUrl, eventSourceFactory)
  const now = useNow(1000)
  const incident = latestIncident(state)

  return (
    <div className="min-h-screen bg-slate-950 px-8 py-6 text-slate-100">
      <div className="mx-auto flex max-w-[1800px] flex-col gap-6">
        <Header connection={state.connection} now={now} rejected={state.rejected} onReset={reset} />
        <PhaseBanner phase={phase} incident={incident} />
        <main className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2 [&>section]:h-full">
            <IncidentTimeline incident={incident} />
          </div>
          <ScoreGauge score={state.score} history={state.history} />
        </main>
        <div className="grid gap-6 lg:grid-cols-3">
          <ServicesGrid services={state.services} />
          <MetricsCards incident={incident} now={now} />
          <VerificationCard verify={state.lastVerification} />
        </div>
        <footer>
          <GrafanaLinks />
        </footer>
      </div>
    </div>
  )
}
