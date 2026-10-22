import { ASSISTANT_URL } from '../config'

/** Onglet « Assistant » : UI de l'assistant RAG servie par l'assistant, en same-origin via le proxy. */
export function AssistantTab({ url = ASSISTANT_URL }: { url?: string }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[13px] text-mute-2">
        Assistant en lecture seule (aucune action sur le système). Nécessite le profil compose <code>ai</code> ; sinon
        l'iframe affiche une erreur 502.
      </p>
      <iframe
        title="Assistant opérateur"
        src={url}
        sandbox="allow-scripts allow-same-origin allow-forms"
        className="h-[75vh] w-full rounded-2xl border border-edge bg-card"
      />
    </div>
  )
}
