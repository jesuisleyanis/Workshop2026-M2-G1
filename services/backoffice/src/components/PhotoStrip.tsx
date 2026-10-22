import type { Pose } from '../api/auth'
import { POSE_LABELS } from '../lib/adminErrors'

const ORDER: Pose[] = ['face', 'gauche', 'droite']

// Trois vignettes (JPEG base64 sans préfixe) : récapitulatif d'enrôlement et photos de référence.
export function PhotoStrip({ photos }: { photos: Partial<Record<Pose, string>> }) {
  return (
    <ul className="grid grid-cols-3 gap-2.5" aria-label="Photos de référence">
      {ORDER.map((pose) => (
        <li key={pose} className="flex flex-col gap-1.5">
          <div className="aspect-[4/3] overflow-hidden rounded-xl border border-line bg-soft">
            {photos[pose] ? (
              <img
                src={`data:image/jpeg;base64,${photos[pose]}`}
                alt={`Photo ${POSE_LABELS[pose].toLowerCase()}`}
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="grid h-full place-items-center text-xs text-ink-4">Absente</div>
            )}
          </div>
          <span className="text-center text-xs text-ink-3">{POSE_LABELS[pose]}</span>
        </li>
      ))}
    </ul>
  )
}
