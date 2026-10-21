import { useSyncExternalStore } from 'react'
import { serviceStatus, type ServiceState } from '../lib/serviceStatus'

export function useServiceStatus(): ServiceState {
  return useSyncExternalStore(serviceStatus.subscribe, serviceStatus.get)
}
