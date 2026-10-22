import { describe, expect, it, vi } from 'vitest'
import { copyText } from './clipboard'

describe('copyText', () => {
  it('utilise navigator.clipboard quand il existe', async () => {
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    expect(await copyText('req-1')).toBe(true)
    expect(writeText).toHaveBeenCalledWith('req-1')
  })

  it('repli execCommand hors contexte sécurisé, échec signalé', async () => {
    vi.stubGlobal('navigator', {})
    const exec = vi.fn(() => false)
    document.execCommand = exec
    expect(await copyText('FR76')).toBe(false)
    expect(exec).toHaveBeenCalledWith('copy')
    expect(document.querySelector('textarea')).toBeNull()
  })
})
