import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { CAPTURE_MAX_SIDE, useCamera } from './useCamera'

// getUserMedia / canvas absents de jsdom : flux et contexte 2D factices.
function fakeStream() {
  const track = { stop: vi.fn() }
  return { track, stream: { getTracks: () => [track] } as unknown as MediaStream }
}

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

let video: HTMLVideoElement
let getUserMedia: ReturnType<typeof vi.fn>

beforeEach(() => {
  video = document.createElement('video')
  vi.spyOn(video, 'play').mockResolvedValue(undefined)
  getUserMedia = vi.fn()
  Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia }, configurable: true })
})
afterEach(() => vi.restoreAllMocks())

describe('useCamera', () => {
  it('coupe un flux arrivé après stop() (aucune caméra orpheline)', async () => {
    const d = deferred<MediaStream>()
    getUserMedia.mockReturnValue(d.promise)
    const { result } = renderHook(() => useCamera({ current: video }))
    const pending = result.current.start()
    result.current.stop()
    const { stream, track } = fakeStream()
    d.resolve(stream)
    await pending
    expect(track.stop).toHaveBeenCalled()
    expect(video.srcObject).toBeNull()
  })

  it('ne garde que le flux du start() le plus récent (double montage StrictMode)', async () => {
    const d1 = deferred<MediaStream>()
    const d2 = deferred<MediaStream>()
    getUserMedia.mockReturnValueOnce(d1.promise).mockReturnValueOnce(d2.promise)
    const { result } = renderHook(() => useCamera({ current: video }))
    const p1 = result.current.start()
    result.current.stop()
    const p2 = result.current.start()
    const s1 = fakeStream()
    const s2 = fakeStream()
    d1.resolve(s1.stream)
    d2.resolve(s2.stream)
    await Promise.all([p1, p2])
    expect(s1.track.stop).toHaveBeenCalled()
    expect(s2.track.stop).not.toHaveBeenCalled()
    expect(video.srcObject).toBe(s2.stream)
  })

  it('capture l’image brute réduite à 640 px sur le plus grand côté', async () => {
    getUserMedia.mockResolvedValue(fakeStream().stream)
    Object.defineProperty(video, 'videoWidth', { value: 1280 })
    Object.defineProperty(video, 'videoHeight', { value: 720 })
    const drawImage = vi.fn()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      drawImage,
    } as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/jpeg;base64,QUJD')
    const { result } = renderHook(() => useCamera({ current: video }))
    await result.current.start()
    expect(result.current.video).toBe(video)
    expect(result.current.capture()).toBe('QUJD')
    expect(drawImage).toHaveBeenCalledWith(video, 0, 0, CAPTURE_MAX_SIDE, 360)
  })

  it('refuse de capturer avant le démarrage', () => {
    const { result } = renderHook(() => useCamera({ current: video }))
    expect(() => result.current.capture()).toThrow('camera_not_ready')
  })
})
