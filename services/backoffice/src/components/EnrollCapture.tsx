import { useRef, useState } from 'react'
import type { FaceFrame, Pose } from '../api/auth'
import type { EnrollmentDetail } from '../api/http'
import { useCamera } from '../hooks/useCamera'
import { adminErrorText, enrollmentRejection, poseLabel, reasonLabel } from '../lib/adminErrors'
import { PhotoStrip } from './PhotoStrip'
import { FaceScanner } from './scanner/FaceScanner'

// Série de captures d'enrôlement partagée par l'assistant « Nouvel agent », le ré-enrôlement
// et l'initialisation : scanner (3 poses) -> récapitulatif (vignettes) -> validation.
// La validation est faite par le parent (`onSubmit`) ; un rejet 422 du serveur (qualité des
// poses, identité incohérente) ramène au scanner avec le détail par pose : la série est refaite.
// Le scanner est démonté pendant le récapitulatif : la caméra n'est allumée que pour la capture.

/** Poses d'enrôlement, dans l'ordre de capture. */
export const ENROLL_POSES: Pose[] = ['face', 'gauche', 'droite']

type Phase = 'scan' | 'recap'

export function EnrollCapture({
  submitLabel = 'Valider l’enrôlement',
  onSubmit,
  onCancel,
}: {
  submitLabel?: string
  /** Doit rejeter avec l'erreur d'API : 422 enrollment_rejected => reprise du scan. */
  onSubmit: (poses: Record<Pose, string>) => Promise<void>
  onCancel: () => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const camera = useCamera(videoRef)

  const [phase, setPhase] = useState<Phase>('scan')
  const [scanKey, setScanKey] = useState(0)
  const [captured, setCaptured] = useState<Record<Pose, string> | null>(null)
  const [rejection, setRejection] = useState<EnrollmentDetail[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [cameraError, setCameraError] = useState(false)

  function onScanComplete(frames: FaceFrame[]) {
    const poses = Object.fromEntries(frames.map((f) => [f.pose, f.image_b64])) as Record<Pose, string>
    setCaptured(poses)
    setRejection(null)
    setError(null)
    setPhase('recap')
  }

  function retake() {
    setCaptured(null)
    setError(null)
    setScanKey((k) => k + 1)
    setPhase('scan')
  }

  async function validate() {
    if (!captured || busy) return
    setBusy(true)
    setError(null)
    try {
      await onSubmit(captured)
    } catch (err) {
      const rejected = enrollmentRejection(err)
      if (rejected) {
        // Reprise des trois poses : nouveau scanner, anciennes images oubliées.
        setRejection(rejected)
        retake()
      } else {
        setError(adminErrorText(err))
      }
    } finally {
      setBusy(false)
    }
  }

  if (phase === 'recap' && captured) {
    return (
      <div className="flex flex-col gap-4">
        <p className="text-sm text-ink-3">Vérifiez que les trois photos sont nettes, de face puis de profil.</p>
        <PhotoStrip photos={captured} />
        {error && (
          <div role="alert" className="rounded-xl bg-ko-bg px-3.5 py-3 text-sm text-ko-fg">
            {error}
          </div>
        )}
        <div className="flex flex-wrap justify-end gap-2.5">
          <button type="button" className="btn-ghost" onClick={onCancel} disabled={busy}>
            Annuler
          </button>
          <button type="button" className="btn-ghost" onClick={retake} disabled={busy}>
            Reprendre les photos
          </button>
          <button type="button" className="btn-primary" onClick={validate} disabled={busy}>
            {busy ? 'Enrôlement…' : submitLabel}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {rejection && (
        <div role="alert" className="rounded-xl bg-warn-bg px-3.5 py-3 text-sm text-warn-fg">
          <p className="font-medium">Photos refusées : refaites les trois poses.</p>
          {rejection.length > 0 && (
            <ul className="mt-1.5 list-disc pl-5">
              {rejection.map((d, i) => (
                <li key={`${d.pose}-${i}`}>
                  {poseLabel(d.pose)} : {reasonLabel(d.reason)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {cameraError && (
        <div role="alert" className="rounded-xl bg-ko-bg px-3.5 py-3 text-sm text-ko-fg">
          Caméra inaccessible sur le PC Hôte.
        </div>
      )}
      <FaceScanner
        key={scanKey}
        mode="enroll"
        poses={ENROLL_POSES}
        camera={camera}
        videoRef={videoRef}
        onComplete={onScanComplete}
        onCancel={onCancel}
        onCameraError={() => setCameraError(true)}
      />
    </div>
  )
}
