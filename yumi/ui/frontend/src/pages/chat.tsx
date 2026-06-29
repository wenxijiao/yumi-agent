import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { PanelLeft, Plus } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { qk, useSessions } from "@/hooks/queries"
import { SessionsSidebar } from "@/components/chat/sessions-sidebar"
import { ChatView } from "@/components/chat/chat-view"
import { Button } from "@/components/ui/button"
import { SimpleTooltip } from "@/components/ui/tooltip"
import { useApp } from "@/store/app"

export function ChatPage() {
  const activeId = useApp((s) => s.activeSessionId)
  const setActiveId = useApp((s) => s.setActiveSessionId)
  const collapsed = useApp((s) => s.chatSidebarCollapsed)
  const toggleSidebar = useApp((s) => s.toggleChatSidebar)
  const { data: sessions = [] } = useSessions()
  const qc = useQueryClient()

  // Page-level auto-select so controls are reachable even when the sidebar is
  // collapsed, and so a stale persisted id (deleted session) falls back cleanly.
  useEffect(() => {
    if (!sessions.length) return
    if (!activeId || !sessions.some((s) => s.session_id === activeId)) {
      setActiveId(sessions[0].session_id)
    }
  }, [sessions, activeId, setActiveId])

  const newChat = async () => {
    try {
      const s = await api.createSession()
      await qc.invalidateQueries({ queryKey: qk.sessions })
      setActiveId(s.session_id)
    } catch {
      toast.error("Could not create a new chat")
    }
  }

  return (
    <div className="flex min-h-0 flex-1">
      {!collapsed && <SessionsSidebar />}
      {activeId ? (
        <ChatView key={activeId} sessionId={activeId} />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <header className="flex items-center gap-2 border-b border-border px-4 py-3">
            {collapsed && (
              <SimpleTooltip label="Show chats">
                <Button variant="ghost" size="icon-sm" onClick={toggleSidebar}>
                  <PanelLeft className="size-4" />
                </Button>
              </SimpleTooltip>
            )}
            <h2 className="text-sm font-semibold">Chat</h2>
          </header>
          <div className="flex flex-1 flex-col items-center justify-center gap-4 text-sm text-muted-foreground">
            <p>No chat selected yet.</p>
            <Button onClick={newChat} className="gap-2">
              <Plus className="size-4" />
              New chat
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
