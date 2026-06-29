import { useEffect } from "react"
import { Command } from "cmdk"
import { useNavigate } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import {
  BarChart3,
  Clock,
  MessagesSquare,
  Moon,
  Plus,
  Search,
  Settings,
  Sun,
  Wrench,
} from "lucide-react"
import { Dialog, DialogContent } from "@/components/ui/dialog"
import { useApp } from "@/store/app"
import { useTheme } from "@/hooks/use-theme"
import { useSessions, qk } from "@/hooks/queries"
import { api } from "@/lib/api"
import { toast } from "sonner"

export function CommandPalette() {
  const open = useApp((s) => s.commandOpen)
  const setOpen = useApp((s) => s.setCommandOpen)
  const setActiveSessionId = useApp((s) => s.setActiveSessionId)
  const { theme, toggle } = useTheme()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: sessions } = useSessions()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setOpen(!useApp.getState().commandOpen)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [setOpen])

  const run = (fn: () => void) => {
    setOpen(false)
    fn()
  }

  const newChat = async () => {
    try {
      const s = await api.createSession()
      await qc.invalidateQueries({ queryKey: qk.sessions })
      setActiveSessionId(s.session_id)
      navigate("/")
    } catch {
      toast.error("Could not create a new chat")
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent hideClose className="max-w-xl overflow-hidden p-0">
        <Command
          className="[&_[cmdk-input-wrapper]]:border-b [&_[cmdk-input-wrapper]]:border-border"
          loop
        >
          <div className="flex items-center gap-2 px-4" cmdk-input-wrapper="">
            <Search className="size-4 text-muted-foreground" />
            <Command.Input
              autoFocus
              placeholder="Search sessions, jump to a page…"
              className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>
          <Command.List className="max-h-[60vh] overflow-y-auto p-2">
            <Command.Empty className="py-8 text-center text-sm text-muted-foreground">
              No results found.
            </Command.Empty>

            <Command.Group heading="Actions" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground">
              <PaletteItem icon={Plus} label="New chat" onSelect={() => run(newChat)} />
              <PaletteItem
                icon={theme === "dark" ? Sun : Moon}
                label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
                onSelect={() => run(toggle)}
              />
            </Command.Group>

            <Command.Group heading="Go to" className="mt-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground">
              <PaletteItem icon={MessagesSquare} label="Chat" onSelect={() => run(() => navigate("/"))} />
              <PaletteItem icon={Wrench} label="Tools" onSelect={() => run(() => navigate("/tools"))} />
              <PaletteItem icon={BarChart3} label="Stats" onSelect={() => run(() => navigate("/stats"))} />
              <PaletteItem icon={Clock} label="Schedules" onSelect={() => run(() => navigate("/timers"))} />
              <PaletteItem icon={Search} label="Memory search" onSelect={() => run(() => navigate("/memory"))} />
              <PaletteItem icon={Settings} label="Settings" onSelect={() => run(() => navigate("/settings"))} />
            </Command.Group>

            {sessions && sessions.length > 0 && (
              <Command.Group heading="Recent chats" className="mt-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground">
                {sessions.slice(0, 8).map((s) => (
                  <PaletteItem
                    key={s.session_id}
                    icon={MessagesSquare}
                    label={s.title}
                    onSelect={() =>
                      run(() => {
                        setActiveSessionId(s.session_id)
                        navigate("/")
                      })
                    }
                  />
                ))}
              </Command.Group>
            )}
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  )
}

function PaletteItem({
  icon: Icon,
  label,
  onSelect,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  onSelect: () => void
}) {
  return (
    <Command.Item
      value={label}
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm outline-none data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
    >
      <Icon className="size-4 text-muted-foreground" />
      <span className="truncate">{label}</span>
    </Command.Item>
  )
}
