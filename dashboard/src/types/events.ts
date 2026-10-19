// Types alignés sur docs/contracts.md §3 (AnomalyEvent) et §1 (événements normalisés remediation_*).
// Le contrat fige l'AnomalyEvent ; l'enveloppe SSE du moteur de remédiation (health, score,
// remediation_*) est documentée dans CAHIER-DES-CHARGES.md (« Flux SSE consommé »).

/** incident_type : énumération figée (contrat §3). */
export const INCIDENT_TYPES = ['service_flood', 'auth_abuse', 'web_attack', 'data_corruption', 'unknown'] as const
export type IncidentType = (typeof INCIDENT_TYPES)[number]

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
      incidentType: IncidentType | null
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

export type StreamMessageKind = StreamMessage['kind']

/** Noms d'événements SSE écoutés (champ `event:`). */
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
  incidentType: IncidentType
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
