import { create } from 'zustand'

/**
 * Global UI state only. Fetched data lives in `useResource`, not here — the
 * store's job is the things that survive navigation.
 */
interface AppState {
  useCase: string
  setUseCase: (useCase: string) => void
}

export const useApp = create<AppState>((set) => ({
  useCase: 'contract_analysis',
  setUseCase: (useCase) => set({ useCase }),
}))
