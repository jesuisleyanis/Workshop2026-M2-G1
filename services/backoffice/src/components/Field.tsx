import { useId, type InputHTMLAttributes } from 'react'

// Champ de formulaire du thème (label + input `field` + message d'erreur relié).
export function Field({ label, error, ...input }: { label: string; error?: string } & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId()
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-[13px] font-medium">
        {label}
      </label>
      <input id={id} className="field" aria-invalid={error ? true : undefined} aria-describedby={error ? `${id}-err` : undefined} {...input} />
      {error && (
        <p id={`${id}-err`} role="alert" className="text-[13px] text-ko-fg">
          {error}
        </p>
      )}
    </div>
  )
}
