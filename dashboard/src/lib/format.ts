/** 4,2 s | 1 min 05 s */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '--'
  if (seconds < 60) return `${seconds.toFixed(1).replace('.', ',')} s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds - m * 60)
  return s === 60 ? `${m + 1} min 00 s` : `${m} min ${String(s).padStart(2, '0')} s`
}

export function formatClock(ms: number): string {
  return new Date(ms).toLocaleTimeString('fr-FR', { hour12: false })
}

export function formatTime(iso: string | null): string {
  if (!iso) return '--:--:--'
  const t = Date.parse(iso)
  return Number.isNaN(t) ? '--:--:--' : formatClock(t)
}

export function formatOffset(seconds: number | null): string {
  if (seconds === null) return ''
  return `+${seconds.toFixed(1).replace('.', ',')} s`
}
