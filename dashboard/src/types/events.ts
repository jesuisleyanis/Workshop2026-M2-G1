// Types alignés sur docs/contracts.md §3 (AnomalyEvent) et §1 (événements normalisés remediation_*).
// Le contrat fige l'AnomalyEvent. Le moteur de remédiation émet UNE seule forme de trame SSE
// (`event: timeline`, voir remediation/timeline.py) ; `parseStreamMessage` la traduit en messages
// internes (ci-dessous). Les kinds `health` / `score` sont alimentés par Prometheus (polling),
// le moteur n'en émet pas. Détail : CAHIER-DES-CHARGES.md §3.

/** incident_type : énumération figée de l'AnomalyEvent (contrat §3). */
export const INCIDENT_TYPES = ['service_flood', 'auth_abuse', 'web_attack', 'data_corruption', 'unknown'] as const
export type IncidentType = (typeof INCIDENT_TYPES)[number]

/**
 * Types d'incident du JOURNAL du moteur (trames SSE, incidents) : ceux du §3 + `manual_action`
 * (action confirmée par un opérateur, POST /manual-actions — contrat « API du moteur »). Jamais émis
 * par le detector : un AnomalyEvent `manual_action` reste refusé.
 */
export const JOURNAL_INCIDENT_TYPES = [...INCIDENT_TYPES, 'manual_action'] as const
export type JournalIncidentType = (typeof JOURNAL_INCIDENT_TYPES)[number]

export interface FeatureContribution {
  name: string
  value: number
  z: number
}

/** Contrat §3 : schéma d'événement d'anomalie (noms de champs conservés tels quels). */
export interface AnomalyEvent {
  schema_version: string
  event_id: string
  ts: string
  source: string
  service: string
  anomaly_score: number
  threshold: number
  incident_type: IncidentType
  features_top: FeatureContribution[]
  evidence: { prometheus_query?: string; loki_query?: string }
}

export type ServiceStatus = 'up' | 'degraded' | 'down' | 'unknown'

export interface ServiceHealth {
  name: string
  status: ServiceStatus
  detail?: string
}

export interface PlannedAction {
  type: string
  params?: Record<string, unknown>
}

export type ActionResult = 'ok' | 'failed' | 'skipped'

export interface VerifyTx {
  ok: boolean
  ts: string
  txId: string | null
  durationMs: number | null
}

/** Messages normalisés issus du flux SSE (après validation). */
export type StreamMessage =
  | { kind: 'health'; ts: string; services: ServiceHealth[] }
  | { kind: 'score'; ts: string; service: string; score: number; threshold: number }
  | { kind: 'anomaly_detected'; incidentId: string; event: AnomalyEvent }
  | {
      kind: 'remediation_started'
      ts: string
      incidentId: string
      incidentType: JournalIncidentType | null
      service: string | null
      actions: PlannedAction[]
      dryRun: boolean
    }
  | {
      kind: 'remediation_action'
      ts: string
      incidentId: string
      action: string
      result: ActionResult
      detail: string | null
      attempt: number | null
    }
  | {
      kind: 'remediation_verified'
      ts: string
      incidentId: string
      verify: VerifyTx
      mttdSeconds: number | null
      mttrSeconds: number | null
    }
  | { kind: 'remediation_failed'; ts: string; incidentId: string; reason: string }
  | { kind: 'verify_tx'; verify: VerifyTx }
  /** Trame `timeline` du moteur sans effet sur l'état (ex. « action en cours », cooldown) : acceptée, jamais comptée comme rejet. */
  | { kind: 'timeline_note'; ts: string; incidentId: string; phase: TimelinePhase; status: TimelineStatus; message: string }

export type StreamMessageKind = StreamMessage['kind']

/** Enveloppe réelle du moteur : `event: timeline` (remediation/timeline.py). */
export const TIMELINE_PHASES = ['detection', 'decision', 'action', 'verification', 'closure', 'escalation'] as const
export type TimelinePhase = (typeof TIMELINE_PHASES)[number]
export const TIMELINE_STATUSES = ['info', 'running', 'ok', 'ko', 'failed', 'skipped', 'dry_run'] as const
export type TimelineStatus = (typeof TIMELINE_STATUSES)[number]
export interface TimelineFrame {
  id: number
  incident_id: string
  incident_type: JournalIncidentType
  ts: string
  phase: TimelinePhase
  status: TimelineStatus
  message: string
  data: Record<string, unknown>
}

/** Kinds internes acceptés directement comme nom d'événement SSE (mock, simulateur, compatibilité). */
export const STREAM_EVENT_NAMES: StreamMessageKind[] = [
  'health',
  'score',
  'anomaly_detected',
  'remediation_started',
  'remediation_action',
  'remediation_verified',
  'remediation_failed',
  'verify_tx',
]

/** Nom d'événement réellement émis par le moteur (une seule enveloppe). */
export const TIMELINE_EVENT_NAME = 'timeline'

/** Noms d'événements SSE écoutés (champ `event:`) : l'enveloppe réelle + les kinds internes. */
export const SSE_EVENT_NAMES: string[] = [TIMELINE_EVENT_NAME, ...STREAM_EVENT_NAMES]

// --- Modèle d'affichage ---------------------------------------------------------

export type Phase = 'before' | 'during' | 'after'

export interface ActionRecord {
  ts: string
  type: string
  result: ActionResult
  detail: string | null
  attempt: number | null
}

export interface Incident {
  id: string
  incidentType: JournalIncidentType
  service: string
  detectedAt: string
  anomaly: AnomalyEvent | null
  decision: { ts: string; actions: PlannedAction[]; dryRun: boolean } | null
  actions: ActionRecord[]
  verification: VerifyTx | null
  failure: { ts: string; reason: string } | null
  mttdSeconds: number | null
  mttrSeconds: number | null
}

export interface ScoreSample {
  ts: string
  service: string
  score: number
  threshold: number
}

export type ConnectionStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'

export interface DashboardState {
  connection: ConnectionStatus
  services: ServiceHealth[]
  score: ScoreSample | null
  history: ScoreSample[]
  incidents: Incident[]
  lastVerification: VerifyTx | null
  /** Messages SSE reçus mais rejetés par la validation (visibilité, pas de perte silencieuse). */
  rejected: number
  /** Incidents écartés par « Réinitialiser la vue » : leurs événements tardifs sont ignorés. */
  dismissed: string[]
}

export type TimelineStepId = 'detection' | 'decision' | 'action' | 'verification'
export type TimelineStepStatus = 'pending' | 'active' | 'done' | 'failed'

export interface TimelineStep {
  id: TimelineStepId
  label: string
  status: TimelineStepStatus
  ts: string | null
  /** Secondes écoulées depuis la détection. */
  offsetSeconds: number | null
  detail: string
}
