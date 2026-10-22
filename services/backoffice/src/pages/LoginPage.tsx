import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode, type RefObject } from 'react'
import { AuthError, identify, submitPassword, verifyFace, type FaceFrame, type Pose, type TokenResult } from '../api/auth'
import { useCamera } from '../hooks/useCamera'
import { formatMinSec, useCountdown } from '../hooks/useCountdown'
import { Brand } from '../components/Brand'
import { DevicePill } from '../components/DevicePill'
import { LedIndicator } from '../components/LedIndicator'
import { FaceScanner } from '../components/scanner/FaceScanner'
import type { Verdict } from '../components/scanner/HudOverlay'
import type { LedState } from '../lib/led'

// Login à étapes du back-office (contrat §5.2) : identifiant -> visage (caméra du PC Hôte)
// -> mot de passe. L'ordre est imposé par le serveur ; l'UI en est le reflet, refroidissements
// compris (le serveur reste l'autorité : un 429 ramène toujours au bon écran).
// Mise en page = login du front ; le seul élément « sci-fi » est le FaceScanner.

type Phase = 'identify' | 'scan' | 'password' | 'granted' | 'locked'
type Notice = { kind: 'info' | 'warn' | 'error'; text: string } | null

/** Verdict « reconnu » affiché dans le scanner avant de passer au mot de passe. */
export const RECOGNIZED_DELAY_MS = 900
/** Écran « accès autorisé » avant l'ouverture du back-office. */
export const GRANTED_DELAY_MS = 1500
/** Durée de blocage serveur après 2 échecs (estimation locale ; Retry-After fait foi). */
export const LOCKOUT_S = 300
// Valeurs par défaut si le serveur ne les fournit pas (BACKOFFICE_REJECT/FAIL_COOLDOWN).
const REJECT_COOLDOWN_S = 30
const FAIL_COOLDOWN_S = 3

const STEPS = ['Identifiant', 'Visage', 'Mot de passe'] as const
const STEP_INDEX: Record<Phase, number> = { identify: 0, scan: 1, password: 2, granted: 3, locked: -1 }

const NOTICE_CLASS: Record<NonNullable<Notice>['kind'], string> = {
  info: 'bg-ok-bg text-ok-fg',
  warn: 'bg-warn-bg text-warn-fg',
  error: 'bg-ko-bg text-ko-fg',
}

const isAuth = (err: unknown, status: number, code?: string): err is AuthError =>
  err instanceof AuthError && err.status === status && (code === undefined || err.code === code)

function errorText(err: unknown): string {
  if (err instanceof AuthError) {
    if (err.code === 'face_service_unavailable') return 'Service de reconnaissance indisponible. Réessayez plus tard.'
    if (err.code === 'challenge_invalid') return 'Session expirée. Recommencez.'
    if (err.status === 0) return 'Service injoignable.'
  }
  return 'Échec de la demande. Réessayez.'
}

export function LoginPage({ onAuthenticated }: { onAuthenticated: (t: TokenResult) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const camera = useCamera(videoRef)
  const countdown = useCountdown()
  const { start: startCountdown, cancel: cancelCountdown } = countdown

  const [phase, setPhase] = useState<Phase>('identify')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [challengeId, setChallengeId] = useState('')
  const [poses, setPoses] = useState<Pose[]>([])
  const [verdict, setVerdict] = useState<Verdict>('idle')
  const [scanKey, setScanKey] = useState(0)
  const [lockedOut, setLockedOut] = useState(false) // dernier rejet visage : plus de tentative
  const [passwordHeld, setPasswordHeld] = useState(false) // refroidissement après mot de passe refusé
  const [notice, setNotice] = useState<Notice>(null)
  const [busy, setBusy] = useState(false)
  const [led, setLedRaw] = useState<{ state: LedState; since: number }>(() => ({ state: 'idle', since: Date.now() }))
  const setLed = (state: LedState) => setLedRaw({ state, since: Date.now() })

  const usernameRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const headingRef = useRef<HTMLHeadingElement>(null)

  // Délais (verdict, accès autorisé) : annulés au démontage.
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([])
  const later = (fn: () => void, ms: number) => {
    timersRef.current.push(setTimeout(fn, ms))
  }
  useEffect(() => {
    const timers = timersRef.current
    return () => timers.forEach(clearTimeout)
  }, [])
  const onAuthRef = useRef(onAuthenticated)
  useEffect(() => {
    onAuthRef.current = onAuthenticated
  })

  // Retour à l'identifiant : scanner démonté (caméra OFF), saisies et challenge oubliés.
  const toIdentify = useCallback(
    (next: Notice) => {
      cancelCountdown()
      setPhase('identify')
      setUsername('')
      setPassword('')
      setChallengeId('')
      setPoses([])
      setVerdict('idle')
      setLockedOut(false)
      setPasswordHeld(false)
      setNotice(next)
    },
    [cancelCountdown],
  )

  const toLocked = useCallback(
    (seconds: number) => {
      setPhase('locked')
      setUsername('')
      setPassword('')
      setChallengeId('')
      setPoses([])
      setVerdict('idle')
      setLockedOut(false)
      setPasswordHeld(false)
      setNotice(null)
      startCountdown(Math.max(1, seconds), () => toIdentify(null))
    },
    [startCountdown, toIdentify],
  )

  // Focus sur l'élément utile de chaque étape (clavier / lecteur d'écran).
  useEffect(() => {
    if (phase === 'identify') usernameRef.current?.focus()
    else if (phase === 'password') passwordRef.current?.focus()
    else headingRef.current?.focus()
  }, [phase])

  const waiting = phase === 'identify' && countdown.left > 0

  async function onIdentify(e: FormEvent) {
    e.preventDefault()
    const name = username.trim()
    if (busy || waiting) return
    if (!name) {
      setNotice({ kind: 'error', text: 'Renseignez votre identifiant.' })
      return
    }
    setBusy(true)
    setNotice(null)
    try {
      const res = await identify(name)
      setChallengeId(res.challenge_id)
      setPoses(res.poses)
      setLed('idle')
      if (res.step === 'face' && res.camera) {
        setVerdict('idle')
        setScanKey((k) => k + 1)
        setPhase('scan')
      } else {
        // Mode dégradé documenté côté auth : facteur visage désactivé.
        setPhase('password')
      }
    } catch (err) {
      if (isAuth(err, 429, 'locked_out')) {
        toLocked(err.retryAfter ?? LOCKOUT_S)
      } else if (isAuth(err, 429)) {
        setNotice({ kind: 'warn', text: 'Refroidissement après un échec. Patientez avant de réessayer.' })
        startCountdown(err.retryAfter ?? REJECT_COOLDOWN_S, () => setNotice(null))
      } else {
        setNotice({ kind: 'error', text: errorText(err) })
      }
    } finally {
      setBusy(false)
    }
  }

  async function onScanComplete(frames: FaceFrame[]) {
    setVerdict('analyzing')
    setNotice(null)
    try {
      const res = await verifyFace(challengeId, frames)
      if (res.recognized) {
        setVerdict('granted')
        setLed('recognized')
        later(() => {
          setPhase('password')
          setNotice({ kind: 'info', text: 'Visage reconnu. Saisissez votre mot de passe.' })
        }, RECOGNIZED_DELAY_MS)
        return
      }
      // Refusé : la caméra RESTE allumée pendant le refroidissement (LED rouge fixe), puis
      // scanner démonté et identifiant vidé — ou écran de blocage si c'était le dernier essai.
      setVerdict('denied')
      setLed('not_recognized')
      const last = res.attempts_left <= 0
      const lockEnd = Date.now() + LOCKOUT_S * 1000
      setLockedOut(last)
      setNotice({
        kind: 'error',
        text: last
          ? 'Visage non reconnu. Trop d’échecs : accès bloqué 5 min.'
          : `Visage non reconnu. Tentative restante : ${res.attempts_left}.`,
      })
      startCountdown(res.cooldown > 0 ? res.cooldown : REJECT_COOLDOWN_S, () =>
        last ? toLocked((lockEnd - Date.now()) / 1000) : toIdentify({ kind: 'info', text: 'Saisissez à nouveau votre identifiant.' }),
      )
    } catch (err) {
      if (isAuth(err, 429, 'locked_out')) toLocked(err.retryAfter ?? LOCKOUT_S)
      else toIdentify({ kind: 'error', text: errorText(err) })
    }
  }

  async function onPassword(e: FormEvent) {
    e.preventDefault()
    if (!password || busy || passwordHeld) return
    setBusy(true)
    setNotice(null)
    try {
      const token = await submitPassword(challengeId, password)
      setPassword('')
      setLed('auth_ok')
      setPhase('granted')
      later(() => onAuthRef.current(token), GRANTED_DELAY_MS)
    } catch (err) {
      if (isAuth(err, 401)) {
        // Rouge ×10 (3 s) côté LED ; champ gelé le temps du refroidissement serveur.
        setLed('auth_fail')
        setPassword('')
        setPasswordHeld(true)
        setNotice({ kind: 'error', text: 'Mot de passe incorrect.' })
        startCountdown(err.retryAfter ?? FAIL_COOLDOWN_S, () =>
          toIdentify({ kind: 'info', text: 'Recommencez depuis l’identifiant.' }),
        )
      } else if (isAuth(err, 403, 'role_not_authorized')) {
        setLed('auth_fail')
        toIdentify({ kind: 'error', text: 'Ce compte n’est pas autorisé pour le back-office.' })
      } else if (isAuth(err, 429, 'locked_out')) {
        toLocked(err.retryAfter ?? LOCKOUT_S)
      } else {
        toIdentify({ kind: 'error', text: errorText(err) })
      }
    } finally {
      setBusy(false)
    }
  }

  const step = STEP_INDEX[phase]
  const noticeEl = notice && (
    <div role={notice.kind === 'error' ? 'alert' : 'status'} className={`rounded-xl px-3.5 py-3 text-sm ${NOTICE_CLASS[notice.kind]}`}>
      {notice.text}
      {passwordHeld && countdown.left > 0 && ` Retour à l’identifiant dans ${countdown.left} s.`}
    </div>
  )

  return (
    <div className="grid min-h-screen [grid-template-columns:repeat(auto-fit,minmax(min(100%,400px),1fr))]">
      <div className="flex flex-col justify-between gap-12 bg-night p-[clamp(28px,4vw,48px)] text-[#f3f4f6]">
        <Brand inverted />
        <div className="flex flex-col gap-4">
          <p className="text-balance text-[clamp(36px,4.4vw,58px)] font-semibold leading-none tracking-[-0.04em]">Accès back-office</p>
          <p className="max-w-[380px] text-[15px] leading-relaxed text-[#a7abb3]">
            Authentification renforcée : identifiant, visage, mot de passe.
          </p>
          <DevicePill />
        </div>
        <div className="flex max-w-[360px] flex-col gap-5 rounded-[22px] border border-[#33363d] bg-night-2 p-5">
          <LedIndicator state={led.state} startedAt={led.since} />
          <ol aria-label="Étapes de connexion" className="flex flex-wrap gap-x-4 gap-y-2 border-t border-[#33363d] pt-4 text-xs">
            {STEPS.map((label, i) => (
              <li
                key={label}
                aria-current={i === step ? 'step' : undefined}
                className={`flex items-center gap-1.5 ${i === step ? 'text-[#f3f4f6]' : 'text-[#a7abb3]'}`}
              >
                <span
                  aria-hidden
                  className={`grid h-5 w-5 place-items-center rounded-full text-[11px] font-semibold tnum ${
                    i < step ? 'bg-[#3a3d45] text-[#f3f4f6]' : i === step ? 'bg-[#f3f4f6] text-night' : 'border border-[#3a3d45]'
                  }`}
                >
                  {i + 1}
                </span>
                {label}
              </li>
            ))}
          </ol>
        </div>
      </div>

      <div className="flex items-center justify-center bg-white p-[clamp(28px,5vw,64px)]">
        <div className={`flex w-full flex-col gap-5 ${phase === 'scan' ? 'max-w-[560px]' : 'max-w-[380px]'}`}>
          {phase === 'identify' && (
            <form onSubmit={onIdentify} noValidate aria-labelledby="login-title" className="flex flex-col gap-5">
              <Heading id="login-title" headingRef={headingRef} sub="Étape 1 sur 3 — saisissez votre identifiant.">
                Connexion
              </Heading>
              {noticeEl}
              <label className="flex flex-col gap-2">
                <span className="text-[13px] font-medium">Identifiant</span>
                <input
                  ref={usernameRef}
                  className="field"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={username}
                  onChange={(ev) => setUsername(ev.target.value)}
                />
              </label>
              <button type="submit" disabled={busy || waiting} className="btn-primary h-[54px] text-base tnum">
                {waiting ? `Patientez ${countdown.left} s` : busy ? 'Vérification…' : 'Continuer'}
              </button>
            </form>
          )}

          {phase === 'scan' && (
            <>
              <Heading id="scan-title" headingRef={headingRef} sub="Étape 2 sur 3 — suivez les consignes à l’écran.">
                Vérification du visage
              </Heading>
              {noticeEl}
              <FaceScanner
                key={scanKey}
                mode="verify"
                poses={poses}
                camera={camera}
                videoRef={videoRef}
                verdict={verdict}
                onComplete={onScanComplete}
                onCancel={verdict === 'idle' ? () => toIdentify(null) : undefined}
                onCameraError={() => toIdentify({ kind: 'error', text: 'Caméra inaccessible sur le PC Hôte.' })}
              >
                {verdict === 'denied' && countdown.left > 0 && (
                  <p role="status" className="text-center text-sm font-medium text-[#fca5a5] tnum">
                    {lockedOut ? `Fermeture de la caméra dans ${countdown.left} s` : `Nouvelle tentative dans ${countdown.left} s`}
                  </p>
                )}
              </FaceScanner>
            </>
          )}

          {phase === 'password' && (
            <form onSubmit={onPassword} noValidate aria-labelledby="password-title" className="flex flex-col gap-5">
              <Heading id="password-title" headingRef={headingRef} sub="Étape 3 sur 3 — saisissez votre mot de passe.">
                Confirmation
              </Heading>
              {noticeEl}
              <label className="flex flex-col gap-2">
                <span className="text-[13px] font-medium">Mot de passe</span>
                <input
                  ref={passwordRef}
                  className="field"
                  type="password"
                  autoComplete="current-password"
                  placeholder="••••••••"
                  disabled={passwordHeld}
                  value={password}
                  onChange={(ev) => setPassword(ev.target.value)}
                />
              </label>
              <button type="submit" disabled={busy || passwordHeld} className="btn-primary h-[54px] text-base">
                {busy ? 'Connexion…' : 'Se connecter'}
              </button>
            </form>
          )}

          {phase === 'granted' && (
            <>
              <Heading id="granted-title" headingRef={headingRef} sub="Identité confirmée en trois étapes.">
                Accès autorisé
              </Heading>
              <div role="status" className="rounded-xl bg-ok-bg px-3.5 py-3 text-sm text-ok-fg">
                Ouverture du back-office…
              </div>
            </>
          )}

          {phase === 'locked' && (
            <>
              <Heading id="locked-title" headingRef={headingRef} sub="Trop de tentatives échouées pour ce poste.">
                Accès bloqué
              </Heading>
              <div role="alert" className="rounded-xl bg-warn-bg px-3.5 py-3 text-sm text-warn-fg tnum">
                Nouvel essai possible dans {formatMinSec(countdown.left)}.
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Heading({
  id,
  headingRef,
  sub,
  children,
}: {
  id: string
  headingRef: RefObject<HTMLHeadingElement | null>
  sub: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {/* tabIndex -1 : cible du focus au changement d'étape, sans entrer dans l'ordre de tabulation. */}
      <h1 id={id} ref={headingRef} tabIndex={-1} className="text-[30px] font-semibold tracking-[-0.03em] outline-none">
        {children}
      </h1>
      <p className="text-[15px] text-ink-3">{sub}</p>
    </div>
  )
}
