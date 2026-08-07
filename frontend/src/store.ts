import { create } from 'zustand'

/**
 * Global UI state only. Fetched data lives in `useResource`, not here — the
 * store's job is the things that survive navigation.
 */
interface AppState {
  useCase: string
  setUseCase: (useCase: string) => void
}

const KEY = 'ccp.useCase'

export const useApp = create<AppState>((set) => ({
  // Survives a reload: the demo moves between two applications and a full page
  // load should not silently drop you back onto a different workload.
  useCase: localStorage.getItem(KEY) ?? 'contract_analysis',
  setUseCase: (useCase) => {
    localStorage.setItem(KEY, useCase)
    set({ useCase })
  },
}))
