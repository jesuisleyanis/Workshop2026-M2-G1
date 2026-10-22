import { describe, expect, it } from 'vitest'
import { POSE_LABELS, poseFromRotation, rotationFromPoints, SEUIL_FACE, SEUIL_PROFIL } from './pose'

// Miroir de services/face-id/tests/test_poses.py.
describe('logique de pose (miroir de face_id/poses.py)', () => {
  it('expose les constantes du contrat et les libellés', () => {
    expect(SEUIL_FACE).toBe(0.1)
    expect(SEUIL_PROFIL).toBe(0.15)
    expect(POSE_LABELS).toEqual({ face: 'Face', gauche: 'Profil gauche', droite: 'Profil droit' })
  })

  it.each([
    [0.0, 'face'],
    [0.1, 'face'],
    [-0.1, 'face'],
    [0.2, 'gauche'],
    [0.15, 'gauche'],
    [-0.2, 'droite'],
    [-0.15, 'droite'],
    [0.12, null],
    [-0.12, null],
    [null, null],
  ])('poseFromRotation(%s) = %s', (rotation, attendu) => {
    expect(poseFromRotation(rotation)).toBe(attendu)
  })

  it('rotation centrée donne zéro', () => {
    expect(rotationFromPoints(0, 100, [50, 50])).toBeCloseTo(0)
  })

  it('utilise la moyenne des points du nez', () => {
    expect(rotationFromPoints(0, 100, [60, 80])).toBeCloseTo(0.2)
  })

  it('rotation négative quand le nez est à gauche', () => {
    expect(rotationFromPoints(10, 110, [30])).toBeCloseTo(-0.3)
  })

  it.each([
    [100, 100],
    [100, 50],
  ])('largeur non positive (%s, %s) donne null', (g, d) => {
    expect(rotationFromPoints(g, d, [75])).toBeNull()
  })

  it('aucun point de nez donne null', () => {
    expect(rotationFromPoints(0, 100, [])).toBeNull()
  })
})
