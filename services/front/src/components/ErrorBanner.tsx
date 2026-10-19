import { userMessage } from '../lib/errorMessages'

interface Props {
  error: unknown
  onRetry?: () => void
}

export function ErrorBanner({ error, onRetry }: Props) {
  return (
    <div role="alert" className="flex items-start justify-between gap-4 rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">
      <p>{userMessage(error)}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="shrink-0 rounded-md border border-red-300 px-3 py-1 text-sm font-medium hover:bg-red-100">
          Réessayer
        </button>
      )}
    </div>
  )
}
