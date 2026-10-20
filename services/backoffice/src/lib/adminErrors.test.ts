import { describe, expect, it } from 'vitest'
import { reasonLabel } from './adminErrors'

describe('reasonLabel', () => {
  it('traduit chaque motif de rejet d’enrôlement de face-id (contrat §5)', () => {
    expect(reasonLabel('missing')).toBe('pose manquante')
    for (const reason of ['no_face', 'multiple_faces', 'wrong_pose', 'inconsistent', 'missing', 'invalid_image']) {
      expect(reasonLabel(reason)).not.toBe(reason)
    }
  })

  it('motif inconnu : renvoyé tel quel', () => {
    expect(reasonLabel('autre')).toBe('autre')
  })
})
