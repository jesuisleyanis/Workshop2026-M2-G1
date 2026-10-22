import type {
  ConnectionStatus,
  DashboardState,
  Incident,
  IncidentType,
  JournalIncidentType,
  Phase,
  ScoreSample,
  ServiceHealth,
  StreamMessage,
  TimelineStep,
  VerifyTx,
} from '../types/events'

/** 2 min à 1 point/s pour ~3 services scorés. */
export const HISTORY_MAX = 360
export const INCIDENTS_MAX = 20
export const DEFAULT_THRESHOLD = 0.6

/** Services affichés avant le premier message `health` (statut inconnu). */
export const DEFAULT_SERVICES: ServiceHealth[] = ['waf', 'front', 'auth', 'payment-api', 'postgres', 'detector'].map(
  (name) => ({ name, status: 'unknown' }),
)

export const initialState: DashboardState = {
  connection: 'connecting',
  services: DEFAULT_SERVICES,
  score: null,
  history: [],
  incidents: [],
  lastVerification: null,
  rejected: 0,
  dismissed: [],
}

export type Action =
  | { type: 'message'; message: StreamMessage }
  | { type: 'connection'; status: ConnectionStatus }
  | { type: 'rejected' }
  | { type: 'reset' }

function newIncident(id: string, ts: string, type: JournalIncidentType = 'unknown', service = 'inconnu'): Incident {
  return {
    id,
    incidentType: type,
    service,
    detectedAt: ts,
    anomaly: null,
    decision: null,
    actions: [],
    verification: null,
    failure: null,
    mttdSeconds: null,
    mttrSeconds: null,
  }
}

function upsert(
  incidents: Incident[],
  id: string,
  ts: string,
  patch: (i: Incident) => Incident,
  defaults?: { type?: JournalIncidentType; service?: string },
): Incident[] {
  const idx = incidents.findIndex((i) => i.id === id)
  if (idx === -1) {
    const created = patch(newIncident(id, ts, defaults?.type, defaults?.service))
    return [...incidents, created].slice(-INCIDENTS_MAX)
  }
  const next = incidents.slice()
  next[idx] = patch(incidents[idx]!)
  return next
}

function pushScore(state: DashboardState, sample: ScoreSample): DashboardState {
  return { ...state, score: sample, history: [...state.history, sample].slice(-HISTORY_MAX) }
}

export function reducer(state: DashboardState, action: Action): DashboardState {
  switch (action.type) {
    case 'connection':
      return { ...state, connection: action.status }
    case 'rejected':
      return { ...state, rejected: state.rejected + 1 }
    case 'reset':
      // Remise à zéro de la vue (reprise de clip) : on écarte les incidents affichés et on
      // garde le contexte (connexion, santé, courbes de score, dernière vérification).
      return {
        ...state,
        incidents: [],
        dismissed: [...state.dismissed, ...state.incidents.map((i) => i.id)].slice(-INCIDENTS_MAX),
      }
    case 'message':
      return applyMessage(state, action.message)
  }
}

function applyMessage(state: DashboardState, m: StreamMessage): DashboardState {
  if ('incidentId' in m && state.dismissed.includes(m.incidentId)) {
    // Incident écarté : seul le score d'une anomalie reste utile à la courbe.
    return m.kind === 'anomaly_detected'
      ? pushScore(state, { ts: m.event.ts, service: m.event.service, score: m.event.anomaly_score, threshold: m.event.threshold })
      : state
  }
  switch (m.kind) {
    case 'health': {
      const byName = new Map(state.services.map((s) => [s.name, s]))
      for (const s of m.services) byName.set(s.name, s)
      return { ...state, services: [...byName.values()] }
    }
    case 'score':
      return pushScore(state, { ts: m.ts, service: m.service, score: m.score, threshold: m.threshold })
    case 'anomaly_detected': {
      const e = m.event
      const withScore = pushScore(state, { ts: e.ts, service: e.service, score: e.anomaly_score, threshold: e.threshold })
      return {
        ...withScore,
        incidents: upsert(
          state.incidents,
          m.incidentId,
          e.ts,
          (i) => ({ ...i, anomaly: e, incidentType: e.incident_type, service: e.service }),
          { type: e.incident_type, service: e.service },
        ),
      }
    }
    case 'remediation_started':
      return {
        ...state,
        incidents: upsert(
          state.incidents,
          m.incidentId,
          m.ts,
          (i) => ({
            ...i,
            incidentType: m.incidentType ?? i.incidentType,
            service: m.service ?? i.service,
            decision: { ts: m.ts, actions: m.actions, dryRun: m.dryRun },
          }),
          { type: m.incidentType ?? 'unknown', service: m.service ?? 'inconnu' },
        ),
      }
    case 'remediation_action':
      return {
        ...state,
        incidents: upsert(state.incidents, m.incidentId, m.ts, (i) => ({
          ...i,
          actions: [...i.actions, { ts: m.ts, type: m.action, result: m.result, detail: m.detail, attempt: m.attempt }],
        })),
      }
    case 'remediation_verified':
      return {
        ...state,
        lastVerification: m.verify,
        incidents: upsert(state.incidents, m.incidentId, m.ts, (i) => ({
          ...i,
          verification: m.verify,
          mttdSeconds: m.mttdSeconds ?? i.mttdSeconds,
          mttrSeconds: m.mttrSeconds ?? i.mttrSeconds,
        })),
      }
    case 'remediation_failed':
      return {
        ...state,
        incidents: upsert(state.incidents, m.incidentId, m.ts, (i) => ({
          ...i,
          failure: { ts: m.ts, reason: m.reason },
        })),
      }
    case 'verify_tx':
      return { ...state, lastVerification: m.verify }
    case 'timeline_note':
      return state // informatif (action en cours, cooldown, dry-run) : rien à changer
  }
}

// --- Dérivations -----------------------------------------------------------------

export function latestIncident(state: Pick<DashboardState, 'incidents'>): Incident | null {
  return state.incidents.at(-1) ?? null
}

/** Incident rétabli = vérification (verify_tx) OK. */
export function isRecovered(i: Incident): boolean {
  return i.verification?.ok === true && i.failure === null
}

/**
 * Phase de la démo (exigence R20) :
 *  - AVANT   : aucun incident observé, système nominal ;
 *  - PENDANT : dernier incident ouvert (détecté, en remédiation ou en échec/escalade) ;
 *  - APRÈS   : dernier incident clos par une vérification verify_tx OK.
 */
export function derivePhase(state: Pick<DashboardState, 'incidents'>): Phase {
  const i = latestIncident(state)
  if (!i) return 'before'
  return isRecovered(i) ? 'after' : 'during'
}

const secondsBetween = (from: string, to: string): number => Math.max(0, (Date.parse(to) - Date.parse(from)) / 1000)

/** MTTR fourni par le moteur, sinon repli : détection -> vérification OK. */
export function incidentMttr(i: Incident): number | null {
  if (i.incidentType === 'manual_action') return null // ni détection ni reprise : aucun MTTR
  if (i.mttrSeconds !== null) return i.mttrSeconds
  if (i.verification?.ok) return secondsBetween(i.detectedAt, i.verification.ts)
  return null
}

const ACTION_LABEL: Record<string, string> = {
  waf_block_ip: 'Blocage IP (WAF)',
  waf_blacklist_ip: 'Blacklist IP (WAF)',
  confirm_waf_block: 'Confirmation du blocage WAF',
  restart_service: 'Redémarrage du service',
  recreate_service: 'Recréation du service',
  tighten_rate_limit: 'Durcissement du rate-limit',
  restore_pg_dump: 'Restauration du dump Postgres',
  dry_run_report: 'Rapport (dry-run)',
  notify_operator: "Notification de l'opérateur",
}
export const actionLabel = (type: string): string => ACTION_LABEL[type] ?? type

export const INCIDENT_LABEL: Record<JournalIncidentType, string> = {
  service_flood: 'Saturation du service',
  auth_abuse: "Abus d'authentification",
  web_attack: 'Attaque web',
  data_corruption: 'Corruption de données',
  unknown: 'Anomalie non classée',
  manual_action: 'Action manuelle (opérateur)',
}

/** Les 4 étapes de la boucle : détection -> décision -> action -> vérification. */
export function buildTimeline(i: Incident): TimelineStep[] {
  const off = (ts: string | null) => (ts ? secondsBetween(i.detectedAt, ts) : null)
  const failed = i.failure !== null
  const verified = i.verification?.ok === true
  const planned = i.decision?.actions.length ?? 0
  const lastAction = i.actions.at(-1) ?? null
  const actionsDone = i.decision !== null && (verified || (planned > 0 && i.actions.length >= planned))
  // Étape qui porte l'échec : la plus avancée atteinte.
  const failStep = i.actions.length > 0 ? 'verification' : i.decision ? 'action' : 'decision'

  const detail = {
    detection: i.anomaly
      ? `${INCIDENT_LABEL[i.incidentType]} sur ${i.service} - score ${i.anomaly.anomaly_score.toFixed(2)} / seuil ${i.anomaly.threshold.toFixed(2)}`
      : `${INCIDENT_LABEL[i.incidentType]} sur ${i.service}`,
    decision: i.decision
      ? `Règle ${i.incidentType} : ${i.decision.actions.map((a) => actionLabel(a.type)).join(', ') || 'aucune action'}${i.decision.dryRun ? ' (dry-run)' : ''}`
      : 'En attente de la décision du moteur',
    action:
      i.actions.length > 0
        ? i.actions.map((a) => `${actionLabel(a.type)} : ${a.result === 'ok' ? 'OK' : a.result === 'skipped' ? 'ignorée' : 'ÉCHEC'}`).join(' - ')
        : 'Aucune action exécutée',
    verification: verified
      ? 'Transaction de vérification réussie'
      : failed
        ? `Échec / escalade : ${i.failure!.reason}`
        : i.verification
          ? 'Transaction de vérification en échec'
          : 'En attente de la transaction de vérification',
  }

  const status = (id: TimelineStep['id']): TimelineStep['status'] => {
    if (failed && failStep === id) return 'failed'
    switch (id) {
      case 'detection':
        return 'done'
      case 'decision':
        return i.decision ? 'done' : failed ? 'failed' : 'active'
      case 'action':
        if (actionsDone) return 'done'
        return i.decision ? (failed ? 'pending' : 'active') : 'pending'
      case 'verification':
        if (verified) return 'done'
        if (i.verification && !i.verification.ok) return 'failed'
        return actionsDone && !failed ? 'active' : 'pending'
    }
  }

  const ts: Record<TimelineStep['id'], string | null> = {
    detection: i.detectedAt,
    decision: i.decision?.ts ?? null,
    action: lastAction?.ts ?? null,
    verification: i.verification?.ts ?? (failed ? i.failure!.ts : null),
  }
  const labels: Record<TimelineStep['id'], string> = {
    detection: 'Détection',
    decision: 'Décision',
    action: 'Action',
    verification: 'Vérification',
  }

  return (['detection', 'decision', 'action', 'verification'] as const).map((id) => {
    const st = status(id)
    const hasTs = st === 'done' || st === 'failed' || (st === 'active' && ts[id] !== null)
    return { id, label: labels[id], status: st, ts: hasTs ? ts[id] : null, offsetSeconds: hasTs ? off(ts[id]) : null, detail: detail[id] }
  })
}

export type ScoreLevel = 'normal' | 'warning' | 'alert'

/** normal < 75 % du seuil <= warning < seuil <= alert. */
export function scoreLevel(score: number, threshold: number): ScoreLevel {
  if (score >= threshold) return 'alert'
  if (score >= threshold * 0.75) return 'warning'
  return 'normal'
}

export function currentThreshold(state: Pick<DashboardState, 'score'>): number {
  return state.score?.threshold ?? DEFAULT_THRESHOLD
}

/** Services ayant émis un score, dans l'ordre d'apparition (onglets de la courbe). */
export function scoredServices(history: ScoreSample[]): string[] {
  return [...new Set(history.map((h) => h.service))]
}

/**
 * Miroir d'affichage de remediation/decision_table.yml (contrat §4). La décision réelle est
 * prise par le moteur ; le panneau surligne la règle et les actions effectivement annoncées.
 */
export const PLAYBOOKS: { type: IncidentType; actions: string[]; nature: string }[] = [
  { type: 'service_flood', actions: ['waf_block_ip', 'restart_service'], nature: 'disponibilité' },
  { type: 'auth_abuse', actions: ['waf_block_ip', 'tighten_rate_limit'], nature: 'disponibilité' },
  { type: 'web_attack', actions: ['confirm_waf_block', 'waf_blacklist_ip'], nature: 'compromission' },
  { type: 'data_corruption', actions: ['restore_pg_dump'], nature: 'intégrité' },
  { type: 'unknown', actions: ['dry_run_report'], nature: 'escalade' },
]

export function verifyOk(v: VerifyTx | null): boolean | null {
  return v ? v.ok : null
}
