import { useMemo, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { MessageSquare, MoreHorizontal, Pencil, Pin, PinOff, Plus, Search, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"
import { qk, useSessions } from "@/hooks/queries"
import { useApp } from "@/store/app"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import type { Session } from "@/lib/types"

export function SessionsSidebar() {
  const { data: sessions = [], isLoading } = useSessions()
  const qc = useQueryClient()
  const activeId = useApp((s) => s.activeSessionId)
  const setActiveId = useApp((s) => s.setActiveSessionId)
  const [search, setSearch] = useState("")
  const [renaming, setRenaming] = useState<Session | null>(null)
  const [renameValue, setRenameValue] = useState("")

  const refresh = () => qc.invalidateQueries({ queryKey: qk.sessions })

  const { pinned, recent } = useMemo(() => {
    const q = search.trim().toLowerCase()
    const match = (s: Session) => !q || s.title.toLowerCase().includes(q)
    return {
      pinned: sessions.filter((s) => s.is_pinned && match(s)),
      recent: sessions.filter((s) => !s.is_pinned && match(s)),
    }
  }, [sessions, search])

  const newChat = async () => {
    try {
      const s = await api.createSession()
      await refresh()
      setActiveId(s.session_id)
    } catch {
      toast.error("Could not create a new chat")
    }
  }

  const togglePin = async (s: Session) => {
    try {
      await api.updateSession(s.session_id, { is_pinned: !s.is_pinned })
      refresh()
    } catch {
      toast.error("Could not update pin")
    }
  }

  const remove = async (s: Session) => {
    try {
      await api.deleteSession(s.session_id)
      const next = sessions.find((x) => x.session_id !== s.session_id)
      await refresh()
      if (activeId === s.session_id) {
        if (next) setActiveId(next.session_id)
        else await newChat()
      }
    } catch {
      toast.error("Could not delete the chat")
    }
  }

  const saveRename = async () => {
    if (!renaming) return
    const title = renameValue.trim()
    setRenaming(null)
    if (!title) return
    try {
      await api.updateSession(renaming.session_id, { title })
      refresh()
    } catch {
      toast.error("Could not rename the chat")
    }
  }

  return (
    <aside className="flex w-[284px] shrink-0 flex-col border-r border-border bg-card/40">
      <div className="space-y-3 p-3">
        <Button className="w-full justify-start gap-2" onClick={newChat}>
          <Plus className="size-4" />
          New chat
        </Button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search chats…"
            className="h-9 pl-8"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {isLoading ? (
          <div className="space-y-1 px-1">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-9 animate-pulse rounded-lg bg-muted/60" />
            ))}
          </div>
        ) : (
          <>
            {pinned.length > 0 && (
              <Group label="Pinned">
                {pinned.map((s) => (
                  <SessionItem
                    key={s.session_id}
                    session={s}
                    active={s.session_id === activeId}
                    onSelect={() => setActiveId(s.session_id)}
                    onPin={() => togglePin(s)}
                    onRename={() => {
                      setRenaming(s)
                      setRenameValue(s.title === "New chat" ? "" : s.title)
                    }}
                    onDelete={() => remove(s)}
                  />
                ))}
              </Group>
            )}
            <Group label={pinned.length ? "Recent" : "Chats"}>
              {recent.map((s) => (
                <SessionItem
                  key={s.session_id}
                  session={s}
                  active={s.session_id === activeId}
                  onSelect={() => setActiveId(s.session_id)}
                  onPin={() => togglePin(s)}
                  onRename={() => {
                    setRenaming(s)
                    setRenameValue(s.title === "New chat" ? "" : s.title)
                  }}
                  onDelete={() => remove(s)}
                />
              ))}
              {recent.length === 0 && pinned.length === 0 && (
                <p className="px-3 py-6 text-center text-sm text-muted-foreground">No chats yet.</p>
              )}
            </Group>
          </>
        )}
      </div>

      <Dialog open={!!renaming} onOpenChange={(o) => !o && setRenaming(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Rename chat</DialogTitle>
          </DialogHeader>
          <Input
            autoFocus
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) saveRename()
            }}
            placeholder="Chat title"
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRenaming(null)}>
              Cancel
            </Button>
            <Button onClick={saveRename}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </aside>
  )
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-2">
      <p className="px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground/70">{label}</p>
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}

function SessionItem({
  session,
  active,
  onSelect,
  onPin,
  onRename,
  onDelete,
}: {
  session: Session
  active: boolean
  onSelect: () => void
  onPin: () => void
  onRename: () => void
  onDelete: () => void
}) {
  return (
    <div
      onClick={onSelect}
      className={cn(
        "group flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors",
        active ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
      )}
    >
      {session.is_pinned ? (
        <Pin className={cn("size-3.5 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
      ) : (
        <MessageSquare className="size-3.5 shrink-0" />
      )}
      <span className="min-w-0 flex-1 truncate">{session.title}</span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
          <button className="rounded p-0.5 opacity-0 transition hover:bg-background/80 group-hover:opacity-100 data-[state=open]:opacity-100">
            <MoreHorizontal className="size-4" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
          <DropdownMenuItem onSelect={onPin}>
            {session.is_pinned ? <PinOff className="size-4" /> : <Pin className="size-4" />}
            {session.is_pinned ? "Unpin" : "Pin"}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={onRename}>
            <Pencil className="size-4" />
            Rename
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem destructive onSelect={onDelete}>
            <Trash2 className="size-4" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
