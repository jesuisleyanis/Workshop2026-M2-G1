import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { FaceScanner, type FaceScannerProps } from './FaceScanner'
import type { Landmarks, PoseDetector } from '../../vision/detector'
import type { Camera } from '../../hooks/useCamera'
import type { Pose } from '../../api/auth'

// jsdom n'a ni vrai <video>, ni canvas, ni rAF réaliste : on pilote tout à la main.
// - rAF remplacé par une file manuelle (frame()) avec un horodatage contrôlé ;
// - timers factices pour le compte à rebours du mode manuel ;
// - détecteur scripté (la pose « vue » est celle qu'on écrit dans `seen`).

let rafQueue = new Map<number, FrameRequestCallback>()
let rafId = 0
let now = 0

function frame(dt = 50) {
  now += dt
  const cbs = [...rafQueue.values()]
  rafQueue = new Map()
  act(() => cbs.forEach((cb) => cb(now)))
}
function frames(n: number, dt = 50) {
  for (let i = 0; i < n; i++) frame(dt)
}

const ROT: Record<Pose, number> = { face: 0, gauche: 0.3, droite: -0.3 }
let seen: Landmarks | null = null
function look(pose: Pose | 'zone_morte', faces = 1) {
  seen = { points: [], rotation: pose === 'zone_morte' ? 0.12 : ROT[pose], faces }
}

interface FakeDetector {
  detect: Mock<PoseDetector['detect']>
  close: Mock<() => void>
}
function fakeDetector(): FakeDetector {
  return { detect: vi.fn<PoseDetector['detect']>(() => seen), close: vi.fn<() => void>() }
}

interface FakeCamera extends Camera {
  start: Mock<Camera['start']>
  stop: Mock<() => void>
  capture: Mock<() => string>
}
function fakeCamera(): FakeCamera {
  let n = 0
  return {
    start: vi.fn<Camera['start']>(() => Promise.resolve()),
    stop: vi.fn<() => void>(),
    capture: vi.fn<() => string>(() => `IMG${++n}`),
    video: null,
  }
}

async function flush() {
  await act(async () => {
    for (let i = 0; i < 10; i++) await Promise.resolve()
  })
}

async function mount(over: Partial<FaceScannerProps> = {}) {
  const det = fakeDetector()
  const camera = fakeCamera()
  const onComplete = vi.fn()
  const props: FaceScannerProps = {
    mode: 'verify',
    poses: ['gauche', 'face', 'droite'],
    camera,
    videoRef: { current: null },
    detectorFactory: () => Promise.resolve(det),
    holdMs: 300,
    onComplete,
    ...over,
  }
  const utils = render(<FaceScanner {...props} />)
  await flush()
  return { ...utils, det, camera, onComplete, props }
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] })
  rafQueue = new Map()
  rafId = 0
  now = 1000
  seen = null
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    rafQueue.set(++rafId, cb)
    return rafId
  })
  vi.stubGlobal('cancelAnimationFrame', (id: number) => {
    rafQueue.delete(id)
  })
  // Pas de canvas dans jsdom : getContext renvoie null sans bruit en console.
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('FaceScanner — capture automatique', () => {
  it('démarre la caméra au montage et capture dans l’ordre demandé après maintien', async () => {
    const { camera, onComplete } = await mount()
    expect(camera.start).toHaveBeenCalledTimes(1)

    look('gauche')
    frames(10) // 500 ms > holdMs 300
    expect(camera.capture).toHaveBeenCalledTimes(1)

    look('face')
    frames(20) // pause inter-pose + maintien
    expect(camera.capture).toHaveBeenCalledTimes(2)

    look('droite')
    frames(20)
    expect(camera.capture).toHaveBeenCalledTimes(3)

    expect(onComplete).toHaveBeenCalledTimes(1)
    expect(onComplete).toHaveBeenCalledWith([
      { pose: 'gauche', image_b64: 'IMG1' },
      { pose: 'face', image_b64: 'IMG2' },
      { pose: 'droite', image_b64: 'IMG3' },
    ])
    // Après la dernière pose : passage en analyse.
    expect(screen.getByText(/analyse biométrique/i)).toBeInTheDocument()
  })

  it('ne capture pas si la pose ne correspond pas à celle attendue', async () => {
    const { camera } = await mount()
    look('droite') // attendu : gauche
    frames(40)
    look('zone_morte') // ni face ni profil
    frames(40)
    expect(camera.capture).not.toHaveBeenCalled()
  })

  it('ne capture pas avec deux visages dans le champ', async () => {
    const { camera } = await mount()
    look('gauche', 2)
    frames(40)
    expect(camera.capture).not.toHaveBeenCalled()
    expect(screen.getByText(/un seul visage/i)).toBeInTheDocument()
  })

  it('ne capture pas une pose maintenue moins longtemps que holdMs', async () => {
    const { camera } = await mount({ holdMs: 1000 })
    look('gauche')
    frames(10) // 500 ms
    look('face')
    frames(10)
    look('gauche')
    frames(10)
    expect(camera.capture).not.toHaveBeenCalled()
  })

  it('ignore une capture qui échoue (caméra pas prête) et réessaie', async () => {
    const { camera, onComplete } = await mount({ poses: ['face'] })
    camera.capture.mockImplementationOnce(() => {
      throw new Error('camera_not_ready')
    })
    look('face')
    frames(10)
    expect(onComplete).not.toHaveBeenCalled()
    frames(20)
    expect(onComplete).toHaveBeenCalledWith([{ pose: 'face', image_b64: 'IMG1' }])
  })
})

describe('FaceScanner — marges de capture (écart MediaPipe / dlib)', () => {
  function lookRot(rotation: number) {
    seen = { points: [], rotation, faces: 1 }
  }

  it('ne capture pas « gauche » à 0.18 (valide pour lib/pose mais sous la marge)', async () => {
    const { camera } = await mount({ poses: ['gauche'] })
    lookRot(0.18)
    frames(40)
    expect(camera.capture).not.toHaveBeenCalled()
    expect(screen.getByTestId('fs-instruction').textContent).toMatch(/encore un peu vers votre gauche/i)
  })

  it('capture « gauche » à 0.25', async () => {
    const { onComplete } = await mount({ poses: ['gauche'] })
    lookRot(0.25)
    frames(10)
    expect(onComplete).toHaveBeenCalledWith([{ pose: 'gauche', image_b64: 'IMG1' }])
  })

  it('ne capture pas « droite » à -0.18, capture à -0.25', async () => {
    const { camera } = await mount({ poses: ['droite'] })
    lookRot(-0.18)
    frames(40)
    expect(camera.capture).not.toHaveBeenCalled()
    lookRot(-0.25)
    frames(10)
    expect(camera.capture).toHaveBeenCalledTimes(1)
  })

  it('ne capture pas « face » à 0.09, capture à 0.05', async () => {
    const { camera } = await mount({ poses: ['face'] })
    lookRot(0.09)
    frames(40)
    expect(camera.capture).not.toHaveBeenCalled()
    lookRot(0.05)
    frames(10)
    expect(camera.capture).toHaveBeenCalledTimes(1)
  })
})

describe('FaceScanner — consigne et accessibilité', () => {
  it('annonce la consigne de la pose attendue dans une région aria-live', async () => {
    await mount()
    look('face')
    frame()
    const live = screen.getByTestId('fs-instruction')
    expect(live).toHaveAttribute('aria-live', 'polite')
    expect(live.textContent).toMatch(/tournez .*gauche/i)
  })

  it('oriente la flèche comme vue dans l’aperçu miroir', async () => {
    await mount({ poses: ['gauche', 'droite', 'face'] })
    look('face')
    frame()
    // « gauche » = gauche de la personne = gauche de l'écran dans l'aperçu miroir.
    expect(screen.getByTestId('fs-arrow')).toHaveAttribute('data-direction', 'left')
    look('gauche')
    frames(20)
    expect(screen.getByTestId('fs-arrow')).toHaveAttribute('data-direction', 'right')
  })

  it('indique l’absence de visage', async () => {
    await mount()
    look('face', 0)
    frame()
    expect(screen.getByTestId('fs-instruction').textContent).toMatch(/placez votre visage/i)
  })

  it('affiche statusText et children dans le cadre', async () => {
    await mount({ statusText: 'TENTATIVE 2/3', children: <p>Nouvel essai dans 12 s</p> })
    expect(screen.getByText('TENTATIVE 2/3')).toBeInTheDocument()
    expect(screen.getByText('Nouvel essai dans 12 s')).toBeInTheDocument()
  })
})

describe('FaceScanner — verdicts', () => {
  it.each([
    ['granted', /identité confirmée/i],
    ['denied', /non reconnu/i],
    ['analyzing', /analyse biométrique/i],
  ] as const)('affiche le verdict %s piloté par le parent', async (verdict, text) => {
    await mount({ verdict })
    expect(screen.getByRole('status', { name: /verdict/i }).textContent).toMatch(text)
  })
})

describe('FaceScanner — mode manuel', () => {
  it('bascule en mode manuel si le détecteur ne charge pas, avec 3-2-1 par pose', async () => {
    const { camera, onComplete } = await mount({ detectorFactory: () => Promise.reject(new Error('wasm')) })
    const button = screen.getByRole('button', { name: /capturer/i })

    for (const pose of ['gauche', 'face', 'droite']) {
      act(() => button.click())
      expect(screen.getByTestId('fs-countdown').textContent).toBe('3')
      act(() => vi.advanceTimersByTime(1000))
      expect(screen.getByTestId('fs-countdown').textContent).toBe('2')
      act(() => vi.advanceTimersByTime(1000))
      expect(screen.getByTestId('fs-countdown').textContent).toBe('1')
      expect(camera.capture).toHaveBeenCalledTimes(['gauche', 'face', 'droite'].indexOf(pose))
      act(() => vi.advanceTimersByTime(1000))
    }
    expect(camera.capture).toHaveBeenCalledTimes(3)
    expect(onComplete).toHaveBeenCalledWith([
      { pose: 'gauche', image_b64: 'IMG1' },
      { pose: 'face', image_b64: 'IMG2' },
      { pose: 'droite', image_b64: 'IMG3' },
    ])
  })

  it('ne capture pas en manuel si un verdict apparaît pendant le compte à rebours', async () => {
    const { camera, rerender, props } = await mount({ detectorFactory: () => Promise.reject(new Error('wasm')) })
    act(() => screen.getByRole('button', { name: /capturer/i }).click())
    rerender(<FaceScanner {...props} verdict="denied" />)
    // Une seconde par act : chaque tic du 3-2-1 est un rendu distinct.
    for (let i = 0; i < 3; i++) act(() => vi.advanceTimersByTime(1000))
    expect(camera.capture).not.toHaveBeenCalled()
  })

  it('bascule en mode manuel si le détecteur plante en cours de route', async () => {
    const { det } = await mount()
    det.detect.mockImplementation(() => {
      throw new Error('gpu_lost')
    })
    frame()
    expect(det.close).toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /capturer/i })).toBeInTheDocument()
    expect(rafQueue.size).toBe(0)
  })

  it('bascule en mode manuel si le détecteur ne répond pas à temps', async () => {
    await mount({ detectorFactory: () => new Promise<PoseDetector>(() => undefined) })
    expect(screen.queryByRole('button', { name: /capturer/i })).toBeNull()
    act(() => vi.advanceTimersByTime(10_000))
    expect(screen.getByRole('button', { name: /capturer/i })).toBeInTheDocument()
  })
})

describe('FaceScanner — cycle de vie', () => {
  it('arrête la caméra et libère le détecteur au démontage', async () => {
    const { camera, det, unmount } = await mount()
    look('face')
    frame()
    unmount()
    expect(camera.stop).toHaveBeenCalled()
    expect(det.close).toHaveBeenCalled()
    expect(rafQueue.size).toBe(0)
  })

  it('signale une caméra inaccessible et propose le retour', async () => {
    const onCameraError = vi.fn()
    const onCancel = vi.fn()
    const camera = fakeCamera()
    camera.start.mockRejectedValue(new Error('NotAllowedError'))
    await mount({ camera, onCameraError, onCancel })
    expect(onCameraError).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('alert').textContent).toMatch(/caméra inaccessible/i)
    act(() => screen.getByRole('button', { name: /annuler/i }).click())
    expect(onCancel).toHaveBeenCalled()
  })
})
