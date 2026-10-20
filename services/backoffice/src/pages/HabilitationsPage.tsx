import { useCallback, useEffect, useState } from 'react'
import { facePhotos, listUsers, revokeFace, setRole, type AgentRole, type AgentRow } from '../api/admin'
import type { Pose } from '../api/auth'
import { ApiError } from '../api/http'
import { EnrollWizard } from '../components/EnrollWizard'
import { PhotoStrip } from '../components/PhotoStrip'
import { adminErrorText } from '../lib/adminErrors'
import { ROLES, ROLE_LABELS } from '../lib/validation'

// Habilitations (rôle admin) : rôles et visages des agents. Le serveur reste l'autorité (403 si
// le jeton n'a pas le rôle admin, 409 `last_admin` si l'action retirerait le dernier admin).

type Wizard = { reenroll?: string } | null
type Photos = { username: string; photos: Record<Pose, string> | null }

/** Statut visage : utilisable, périmé (réenrôlement requis) ou absent. */
function faceStatus(row: AgentRow): { label: string; ok: boolean } {
  if (row.enrolled) return { label: formatEnrolled(row), ok: true }
  if (row.stale) return { label: 'Réenrôlement requis', ok: false }
  return { label: 'Non enrôlé', ok: false }
}

function formatEnrolled(row: AgentRow): string {
  const date = row.enrolled_at ? new Date(row.enrolled_at) : null
  const when = date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString('fr-FR') : row.enrolled_at
  return `Enrôlé${when ? ` le ${when}` : ''}${row.enrolled_by ? ` par ${row.enrolled_by}` : ''}`
}

export function HabilitationsPage({ token, onUnauthorized }: { token: string; onUnauthorized?: () => void }) {
  const [rows, setRows] = useState<AgentRow[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null) // identifiant en cours d'action
  const [wizard, setWizard] = useState<Wizard>(null)
  const [confirmRevoke, setConfirmRevoke] = useState<string | null>(null)
  const [photos, setPhotos] = useState<Photos | null>(null)
  const [reloadTick, setReloadTick] = useState(0)

  /** Erreur d'API : 401 => session expirée (retour au login), sinon message en clair. */
  const fail = useCallback(
    (err: unknown): string => {
      if (err instanceof ApiError && err.status === 401) onUnauthorized?.()
      return adminErrorText(err)
    },
    [onUnauthorized],
  )

  useEffect(() => {
    let alive = true
    listUsers(token).then(
      (list) => {
        if (!alive) return
        setRows(list)
        setLoadError(null)
      },
      (err) => alive && setLoadError(fail(err)),
    )
    return () => {
      alive = false
    }
  }, [token, reloadTick, fail])

  const reload = () => setReloadTick((t) => t + 1)

  async function changeRole(row: AgentRow, role: AgentRole) {
    if (role === row.role || busy) return
    setNotice(null)
    setBusy(row.username)
    try {
      await setRole(token, row.username, role)
      setRows((rs) => rs && rs.map((r) => (r.username === row.username ? { ...r, role } : r)))
    } catch (err) {
      setNotice(fail(err))
    } finally {
      setBusy(null)
    }
  }

  async function revoke(username: string) {
    setNotice(null)
    setBusy(username)
    try {
      await revokeFace(token, username)
      if (photos?.username === username) setPhotos(null)
      reload()
    } catch (err) {
      setNotice(fail(err))
    } finally {
      setConfirmRevoke(null)
      setBusy(null)
    }
  }

  async function togglePhotos(username: string) {
    if (photos?.username === username) {
      setPhotos(null)
      return
    }
    setNotice(null)
    setPhotos({ username, photos: null })
    try {
      const res = await facePhotos(token, username)
      setPhotos((cur) => (cur?.username === username ? { username, photos: res.photos } : cur))
    } catch (err) {
      setPhotos(null)
      setNotice(fail(err))
    }
  }

  function closeWizard(refresh: boolean) {
    setWizard(null)
    if (refresh) reload()
  }

  return (
    <section aria-labelledby="hab-title" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 id="hab-title" className="text-[26px] font-semibold tracking-[-0.03em]">
            Habilitations
          </h1>
          <p className="text-sm text-ink-3">Rôles et visages enrôlés des agents du back-office.</p>
        </div>
        <button type="button" className="btn-primary" onClick={() => setWizard({})}>
          Nouvel agent
        </button>
      </div>

      {notice && (
        <div role="alert" className="rounded-xl bg-ko-bg px-3.5 py-3 text-sm text-ko-fg">
          {notice}
        </div>
      )}

      {confirmRevoke && (
        <div
          role="alertdialog"
          aria-labelledby="revoke-title"
          className="flex flex-col gap-3 rounded-2xl border border-line bg-warn-bg p-4 text-warn-fg"
        >
          <p id="revoke-title" className="text-sm font-medium">
            Révoquer le visage de {confirmRevoke} ? Ce compte ne pourra plus passer l’étape de reconnaissance faciale avant un nouvel enrôlement.
          </p>
          <div className="flex gap-2.5">
            <button type="button" className="btn-primary" onClick={() => revoke(confirmRevoke)} disabled={busy !== null}>
              Confirmer la révocation
            </button>
            <button type="button" className="btn-ghost" onClick={() => setConfirmRevoke(null)} disabled={busy !== null}>
              Annuler
            </button>
          </div>
        </div>
      )}

      {rows === null ? (
        loadError ? (
          <div role="alert" className="flex flex-col items-start gap-3 rounded-2xl bg-ko-bg p-4 text-ko-fg">
            <span className="text-[15px] font-semibold">Chargement impossible</span>
            <span className="text-[13px]">{loadError}</span>
            <button type="button" className="btn-ghost" onClick={reload}>
              Réessayer
            </button>
          </div>
        ) : (
          <div role="status" aria-label="Chargement des agents" className="h-40 animate-pulse rounded-2xl bg-[#eceef1]" />
        )
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-line bg-frame">
          <table aria-label="Agents" className="w-full min-w-[720px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-3">
                <th scope="col" className="px-4 py-3 font-medium">
                  Identifiant
                </th>
                <th scope="col" className="px-4 py-3 font-medium">
                  Rôle
                </th>
                <th scope="col" className="px-4 py-3 font-medium">
                  Visage
                </th>
                <th scope="col" className="px-4 py-3 text-right font-medium">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.username} className="border-b border-line last:border-0">
                  <th scope="row" className="px-4 py-3 font-medium">
                    {row.username}
                  </th>
                  <td className="px-4 py-3">
                    <select
                      aria-label={`Rôle de ${row.username}`}
                      className="h-10 rounded-xl border-[1.5px] border-line bg-white px-3 text-sm outline-none focus:border-night disabled:opacity-60"
                      value={row.role}
                      disabled={busy === row.username}
                      onChange={(e) => changeRole(row, e.target.value as AgentRole)}
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABELS[r]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-md px-2 py-0.5 text-[12px] ${faceStatus(row).ok ? 'bg-ok-bg text-ok-fg' : 'bg-warn-bg text-warn-fg'}`}
                      title={row.stale && !row.enrolled ? 'Gabarit issu d’un autre modèle : ce compte ne peut plus se connecter' : undefined}
                    >
                      {faceStatus(row).label}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap justify-end gap-2">
                      {row.enrolled && (
                        <button
                          type="button"
                          className="btn-ghost !h-9"
                          aria-label={`${photos?.username === row.username ? 'Masquer les photos de' : 'Voir les photos de'} ${row.username}`}
                          onClick={() => togglePhotos(row.username)}
                        >
                          {photos?.username === row.username ? 'Masquer photos' : 'Voir photos'}
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn-ghost !h-9"
                        aria-label={`${row.enrolled || row.stale ? 'Ré-enrôler' : 'Enrôler'} le visage de ${row.username}`}
                        onClick={() => setWizard({ reenroll: row.username })}
                      >
                        {row.enrolled || row.stale ? 'Ré-enrôler' : 'Enrôler'}
                      </button>
                      {(row.enrolled || row.stale) && (
                        <button
                          type="button"
                          className="btn-ghost !h-9 !text-ko-fg"
                          aria-label={`Révoquer le visage de ${row.username}`}
                          onClick={() => setConfirmRevoke(row.username)}
                        >
                          Révoquer
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {photos && (
        <div className="flex flex-col gap-3 rounded-2xl border border-line bg-frame p-4">
          <h2 className="text-[15px] font-semibold">Photos de référence de {photos.username}</h2>
          {photos.photos ? (
            <div className="max-w-[480px]">
              <PhotoStrip photos={photos.photos} />
            </div>
          ) : (
            <div role="status" aria-label="Chargement des photos" className="h-28 max-w-[480px] animate-pulse rounded-xl bg-[#eceef1]" />
          )}
        </div>
      )}

      {wizard && (
        <EnrollWizard
          token={token}
          reenroll={wizard.reenroll}
          takenUsernames={rows?.map((r) => r.username)}
          onClose={closeWizard}
        />
      )}
    </section>
  )
}
