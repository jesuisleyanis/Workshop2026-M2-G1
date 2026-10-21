import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import { serviceStatus } from '../lib/serviceStatus'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  serviceStatus.reset()
  sessionStorage.clear()
  localStorage.clear()
})
