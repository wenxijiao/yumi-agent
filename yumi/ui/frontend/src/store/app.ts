import { create } from "zustand"

interface AppState {
  commandOpen: boolean
  setCommandOpen: (v: boolean) => void
  /** The chat session currently open in the Chat view. */
  activeSessionId: string | null
  setActiveSessionId: (id: string | null) => void
  /** Whether spoken replies (TTS) auto-play after each assistant turn. */
  voiceReplies: boolean
  setVoiceReplies: (v: boolean) => void
  /** Collapse the chat sessions sidebar to give the conversation more room. */
  chatSidebarCollapsed: boolean
  toggleChatSidebar: () => void
}

const VOICE_KEY = "yumi-voice-replies"
const SIDEBAR_KEY = "yumi-chat-sidebar-collapsed"
const ACTIVE_SESSION_KEY = "yumi-active-session"

export const useApp = create<AppState>((set, get) => ({
  commandOpen: false,
  setCommandOpen: (v) => set({ commandOpen: v }),
  // Persisted so a refresh reopens the last chat instead of an empty pane.
  activeSessionId: (typeof localStorage !== "undefined" && localStorage.getItem(ACTIVE_SESSION_KEY)) || null,
  setActiveSessionId: (id) => {
    if (id) localStorage.setItem(ACTIVE_SESSION_KEY, id)
    else localStorage.removeItem(ACTIVE_SESSION_KEY)
    set({ activeSessionId: id })
  },
  voiceReplies: typeof localStorage !== "undefined" && localStorage.getItem(VOICE_KEY) === "1",
  setVoiceReplies: (v) => {
    localStorage.setItem(VOICE_KEY, v ? "1" : "0")
    set({ voiceReplies: v })
  },
  chatSidebarCollapsed: typeof localStorage !== "undefined" && localStorage.getItem(SIDEBAR_KEY) === "1",
  toggleChatSidebar: () => {
    const next = !get().chatSidebarCollapsed
    localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0")
    set({ chatSidebarCollapsed: next })
  },
}))
