import { SessionsSidebar } from "@/components/chat/sessions-sidebar"
import { ChatView } from "@/components/chat/chat-view"
import { useApp } from "@/store/app"

export function ChatPage() {
  const activeId = useApp((s) => s.activeSessionId)
  const collapsed = useApp((s) => s.chatSidebarCollapsed)
  return (
    <div className="flex min-h-0 flex-1">
      {!collapsed && <SessionsSidebar />}
      {activeId ? (
        <ChatView key={activeId} sessionId={activeId} />
      ) : (
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          Select or start a chat to begin.
        </div>
      )}
    </div>
  )
}
