import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { AuthError, identify, submitPassword, verifyFace, type Pose, type TokenResult } from '../api/auth'
import { useCamera, type Camera } from '../hooks/useCamera'
import { LedIndicator } from '../components/LedIndicator'
import type { LedState } from '../lib/led'

type Phase = 'identify' | 'scanning' | 'password' | 'locked'
type Notice = { kind: 'info' | 'error'; text: string } | null

// Login à étapes du back-office (contrat §5.2) : identifiant -> visage (caméra du PC Hôte)
// -> mot de passe. L'ordre est imposé par le serveur ; l'UI en est le reflet.
export function LoginPage({ onAuthenticated }: { onAuthenticated: (t: TokenResult) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const camera: Camera = useCamera(videoRef)
  const [phase, setPhase] = useState<Phase>('identify')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [challengeId, setChallengeId] = useState('')
  const [poses, setPoses] = useState<Pose[]>([])
  const [led, setLed] = useState<LedState>('idle')
  const [notice, setNotice] = useState<Notice>(null)
  const [busy, setBusy] = useState(false)
  const [lockLeft, setLockLeft] = useState(0)

  const resetToIdentify = useCallback((message: Notice) => {
    setPhase('identify')
    setUsername('')
    setPassword('')
    setChallengeId('')
    setPoses([])
    setNotice(message)
  }, [])

  // Caméra : démarrée quand le <video> de l'étape scan est monté, coupée dès qu'on en sort
  // (et au démontage). Si getUserMedia échoue, on repart à l'identifiant (pas d'état bloqué).
  useEffect(() => {
    if (phase !== 'scanning') {
      camera.stop()
      return
    }
    let cancelled = false
    camera.start().catch(() => {
      if (!cancelled) resetToIdentify({ kind: 'error', text: 'Caméra inaccessible sur le PC Hôte.' })
    })
    return () => {
      cancelled = true
      camera.stop()
    }
  }, [phase, camera, resetToIdentify])

  // Décompte du blocage 5 min.
  useEffect(() => {
    if (phase !== 'locked' || lockLeft <= 0) return
    const id = setInterval(() => setLockLeft((n) => Math.max(n - 1, 0)), 1000)
    return () => clearInterval(id)
  }, [phase, lockLeft])
  // Fin du blocage : retour à l'identification (différé pour ne pas faire un setState synchrone).
  useEffect(() => {
    if (phase !== 'locked' || lockLeft > 0) return
    const t = setTimeout(() => resetToIdentify(null), 0)
    return () => clearTimeout(t)
  }, [phase, lockLeft, resetToIdentify])

  async function onIdentify(e: FormEvent) {
    e.preventDefault()
    if (!username.trim() || busy) return
    setBusy(true)
    setNotice(null)
    try {
      const res = await identify(username.trim())
      setChallengeId(res.challenge_id)
      setPoses(res.poses)
      setLed('idle')
      // L'effet [phase] démarre la caméra une fois le <video> monté (évite une course sur le ref).
      setPhase(res.camera && res.step === 'face' ? 'scanning' : 'password')
    } catch (err) {
      if (err instanceof AuthError && err.status === 429) {
        setLockLeft(err.retryAfter ?? 300)
        setPhase('locked')
      } else {
        setNotice({ kind: 'error', text: 'Échec de la demande. Réessayez.' })
      }
    } finally {
      setBusy(false)
    }
  }

  async function onScan() {
    if (busy) return
    setBusy(true)
    setNotice(null)
    try {
      // Version transitoire (réécrite en T8 avec le FaceScanner) : une capture par pose demandée.
      const frames = poses.map((pose) => ({ pose, image_b64: camera.capture() }))
      const res = await verifyFace(challengeId, frames)
      if (res.recognized) {
        camera.stop()
        setLed('recognized')
        setPhase('password')
        setNotice({ kind: 'info', text: 'Visage reconnu. Saisissez votre mot de passe.' })
      } else {
        camera.stop()
        setLed('not_recognized')
        const left = res.attempts_left
        resetToIdentify({
          kind: 'error',
          text:
            left > 0
              ? `Visage non reconnu. Reprise(s) restante(s) : ${left}.`
              : 'Visage non reconnu.',
        })
      }
    } catch (err) {
      camera.stop()
      if (err instanceof AuthError && err.code === 'face_service_unavailable') {
        resetToIdentify({ kind: 'error', text: 'Service de reconnaissance indisponible.' })
      } else {
        resetToIdentify({ kind: 'error', text: 'Session expirée. Recommencez.' })
      }
    } finally {
      setBusy(false)
    }
  }

  async function onPassword(e: FormEvent) {
    e.preventDefault()
    if (!password || busy) return
    setBusy(true)
    setNotice(null)
    try {
      const token = await submitPassword(challengeId, password)
      setLed('auth_ok')
      onAuthenticated(token)
    } catch (err) {
      const e2 = err instanceof AuthError ? err : null
      if (e2?.code === 'role_not_authorized') {
        setLed('auth_fail')
        resetToIdentify({ kind: 'error', text: "Ce compte n'est pas autorisé pour le back-office." })
      } else {
        setLed('auth_fail')
        resetToIdentify({ kind: 'error', text: 'Mot de passe incorrect. Recommencez.' })
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[420px] flex-col justify-center gap-6 p-4">
      <div>
        <p className="text-sm font-semibold text-ink-3">RESILIENCE-ALPHA</p>
        <h1 className="text-[28px] font-semibold tracking-[-0.03em]">Back-office</h1>
        <p className="text-[15px] text-ink-3">Accès réservé — authentification renforcée.</p>
      </div>

      <LedIndicator state={led} />

      {notice && (
        <div
          role={notice.kind === 'error' ? 'alert' : 'status'}
          className={
            notice.kind === 'error'
              ? 'rounded-xl bg-ko-bg px-3.5 py-3 text-sm text-ko-fg'
              : 'rounded-xl bg-ok-bg px-3.5 py-3 text-sm text-ok-fg'
          }
        >
          {notice.text}
        </div>
      )}

      {phase === 'identify' && (
        <form onSubmit={onIdentify} className="flex flex-col gap-4" aria-label="identification">
          <label className="flex flex-col gap-2">
            <span className="text-[13px] font-medium">Identifiant</span>
            <input
              className="field"
              autoComplete="username"
              value={username}
              onChange={(ev) => setUsername(ev.target.value)}
            />
          </label>
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? 'Vérification…' : 'Continuer'}
          </button>
        </form>
      )}

      {phase === 'scanning' && (
        <div className="flex flex-col gap-4">
          <video
            ref={videoRef}
            data-testid="camera"
            autoPlay
            muted
            playsInline
            className="aspect-[4/3] w-full rounded-xl bg-night object-cover"
          />
          <p className="text-sm text-ink-3">Regardez la caméra pour confirmer votre identité.</p>
          <button type="button" className="btn-primary w-full" onClick={onScan} disabled={busy}>
            {busy ? 'Analyse…' : 'Scanner mon visage'}
          </button>
        </div>
      )}

      {phase === 'password' && (
        <form onSubmit={onPassword} className="flex flex-col gap-4" aria-label="connexion">
          <label className="flex flex-col gap-2">
            <span className="text-[13px] font-medium">Mot de passe</span>
            <input
              className="field"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(ev) => setPassword(ev.target.value)}
            />
          </label>
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? 'Connexion…' : 'Se connecter'}
          </button>
        </form>
      )}

      {phase === 'locked' && (
        <div role="alert" className="rounded-xl bg-warn-bg px-3.5 py-3 text-sm text-warn-fg">
          Trop de tentatives échouées. Accès bloqué {lockLeft > 0 ? `(${lockLeft}s)` : ''}.
        </div>
      )}
    </div>
  )
}
