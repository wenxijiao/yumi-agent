import { create } from "zustand"
import { api } from "@/lib/api"

type Theme = "dark" | "light"

const STORAGE_KEY = "yumi-theme"

function apply(theme: Theme) {
  const root = document.documentElement
  root.classList.toggle("dark", theme === "dark")
  root.style.colorScheme = theme
}

interface ThemeStore {
  theme: Theme
  resolved: Theme
  setTheme: (t: Theme) => void
  toggle: () => void
  /** Pull the persisted preference from the server (overrides local on success). */
  hydrate: () => Promise<void>
}

const initial: Theme =
  (typeof localStorage !== "undefined" && (localStorage.getItem(STORAGE_KEY) as Theme)) || "dark"
apply(initial)

export const useTheme = create<ThemeStore>((set, get) => ({
  theme: initial,
  resolved: initial,
  setTheme: (t) => {
    apply(t)
    localStorage.setItem(STORAGE_KEY, t)
    set({ theme: t, resolved: t })
    api.setUiPrefs(t === "dark").catch(() => {})
  },
  toggle: () => get().setTheme(get().theme === "dark" ? "light" : "dark"),
  hydrate: async () => {
    try {
      const { dark_mode } = await api.getUiPrefs()
      const t: Theme = dark_mode ? "dark" : "light"
      apply(t)
      localStorage.setItem(STORAGE_KEY, t)
      set({ theme: t, resolved: t })
    } catch {
      // offline / not configured — keep local preference
    }
  },
}))
