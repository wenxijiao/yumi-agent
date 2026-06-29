import { useState } from "react"
import {
  Wrench,
  RefreshCw,
  Shield,
  ShieldCheck,
  PackageSearch,
  Cpu,
  WifiOff,
  ChevronDown,
} from "lucide-react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { PageHeader, PageBody } from "@/components/layout/page"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import { SimpleTooltip } from "@/components/ui/tooltip"
import { useTools, qk } from "@/hooks/queries"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { EdgeDevice } from "@/lib/types"

// ── ToolCard ──────────────────────────────────────────────────────────────────

interface ToolCardProps {
  name: string
  description: string
  disabled: boolean
  requireConfirmation: boolean
  isPending: boolean
  isConfirmPending: boolean
  onToggle: (nextDisabled: boolean) => void
  onConfirm: (nextRequire: boolean) => void
}

function ToolCard({
  name,
  description,
  disabled,
  requireConfirmation,
  isPending,
  isConfirmPending,
  onToggle,
  onConfirm,
}: ToolCardProps) {
  return (
    <Card
      className={cn(
        "flex flex-col rounded-xl shadow-sm transition-all",
        disabled
          ? "border-dashed border-border/60 bg-muted/15 opacity-60 hover:opacity-100"
          : "hover:border-border/80",
      )}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle
              className={cn(
                "min-w-0 break-all font-mono text-sm font-medium leading-tight",
                disabled && "text-muted-foreground",
              )}
            >
              {name}
            </CardTitle>
            {disabled && (
              <Badge variant="muted" className="mt-1.5">
                Disabled
              </Badge>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <SimpleTooltip
              label={
                requireConfirmation
                  ? "Confirmation required — click to remove"
                  : "Click to require confirmation before each call"
              }
              side="top"
            >
              <Button
                variant="ghost"
                size="icon-sm"
                disabled={isConfirmPending}
                onClick={() => onConfirm(!requireConfirmation)}
                className={cn(
                  "transition-colors",
                  requireConfirmation
                    ? "text-warning hover:text-warning/80"
                    : "text-muted-foreground hover:text-foreground",
                )}
                aria-label="Toggle confirmation requirement"
              >
                {requireConfirmation ? (
                  <ShieldCheck className="size-4" />
                ) : (
                  <Shield className="size-4" />
                )}
              </Button>
            </SimpleTooltip>
            <SimpleTooltip label={disabled ? "Enable tool" : "Disable tool"} side="top">
              <Switch
                checked={!disabled}
                disabled={isPending}
                onCheckedChange={(checked) => onToggle(!checked)}
                aria-label={`${disabled ? "Enable" : "Disable"} ${name}`}
              />
            </SimpleTooltip>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <p className="line-clamp-2 text-xs text-muted-foreground">
          {description || "No description provided."}
        </p>
      </CardContent>
    </Card>
  )
}

// ── EdgeDeviceCard ─────────────────────────────────────────────────────────────

interface EdgeDeviceCardProps {
  device: EdgeDevice
  pending: Record<string, boolean>
  searchActive: boolean
  onToggle: (toolFullName: string, nextDisabled: boolean) => void
  onConfirm: (toolFullName: string, nextRequire: boolean) => void
}

function EdgeDeviceCard({ device, pending, searchActive, onToggle, onConfirm }: EdgeDeviceCardProps) {
  // Long tool lists collapse by default; a search forces every device open.
  const [userOpen, setUserOpen] = useState(device.tools.length <= 6)
  const open = searchActive || userOpen
  const enabledCount = device.tools.filter((t) => !t.disabled).length

  return (
    <Card className="overflow-hidden rounded-xl shadow-sm">
      <button
        type="button"
        onClick={() => setUserOpen((o) => !o)}
        disabled={device.tools.length === 0}
        className="flex w-full items-center gap-2 px-5 py-3.5 text-left transition-colors hover:bg-accent/40 disabled:cursor-default disabled:hover:bg-transparent"
      >
        <Cpu className="size-4 shrink-0 text-muted-foreground" />
        <CardTitle className="text-sm font-semibold">{device.edge_name}</CardTitle>
        <Badge variant={device.online ? "success" : "muted"}>
          {device.online ? "Online" : "Offline"}
        </Badge>
        <span className="ml-auto text-xs text-muted-foreground">
          {enabledCount}/{device.tools.length} enabled
        </span>
        {device.tools.length > 0 && (
          <ChevronDown
            className={cn(
              "size-4 shrink-0 text-muted-foreground transition-transform",
              open && "rotate-180",
            )}
          />
        )}
      </button>

      {device.tools.length > 0 && open && (
        <CardContent className="pt-0">
          <div className="flex flex-col">
            {device.tools.map((tool, idx) => (
              <div key={tool.full_name} className={cn(tool.disabled && "opacity-55 hover:opacity-100")}>
                {idx > 0 && <Separator className="my-2" />}
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p
                      className={cn(
                        "break-all font-mono text-xs font-medium leading-tight",
                        tool.disabled && "text-muted-foreground",
                      )}
                    >
                      {tool.name}
                      {tool.disabled && (
                        <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">
                          off
                        </span>
                      )}
                    </p>
                    {tool.description && (
                      <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                        {tool.description}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <SimpleTooltip
                      label={
                        tool.require_confirmation
                          ? "Confirmation required — click to remove"
                          : "Click to require confirmation before each call"
                      }
                      side="top"
                    >
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        disabled={!!pending[tool.full_name + "_conf"]}
                        onClick={() => onConfirm(tool.full_name, !tool.require_confirmation)}
                        className={cn(
                          "h-7 w-7 transition-colors",
                          tool.require_confirmation
                            ? "text-warning hover:text-warning/80"
                            : "text-muted-foreground hover:text-foreground",
                        )}
                        aria-label="Toggle confirmation requirement"
                      >
                        {tool.require_confirmation ? (
                          <ShieldCheck className="size-3.5" />
                        ) : (
                          <Shield className="size-3.5" />
                        )}
                      </Button>
                    </SimpleTooltip>
                    <SimpleTooltip
                      label={tool.disabled ? "Enable tool" : "Disable tool"}
                      side="top"
                    >
                      <Switch
                        checked={!tool.disabled}
                        disabled={!!pending[tool.full_name]}
                        onCheckedChange={(checked) => onToggle(tool.full_name, !checked)}
                        aria-label={`${tool.disabled ? "Enable" : "Disable"} ${tool.name}`}
                      />
                    </SimpleTooltip>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      )}

      {device.tools.length === 0 && !device.online && (
        <CardContent className="pt-0">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <WifiOff className="size-3.5" />
            <span>Device is offline — no tools available.</span>
          </div>
        </CardContent>
      )}
    </Card>
  )
}

// ── Loading skeleton ───────────────────────────────────────────────────────────

function ToolsSkeleton() {
  return (
    <PageBody>
      <div className="mb-6 flex gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-6 w-24 rounded-full" />
        ))}
      </div>
      <div className="mb-3">
        <Skeleton className="h-5 w-28 rounded" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-28 rounded-xl" />
        ))}
      </div>
    </PageBody>
  )
}

// ── ToolsPage ─────────────────────────────────────────────────────────────────

export function ToolsPage() {
  const { data, isLoading, isError, refetch } = useTools()
  const qc = useQueryClient()
  const [search, setSearch] = useState("")
  const [pending, setPending] = useState<Record<string, boolean>>({})

  // --- handlers ---

  async function handleToggle(toolName: string, nextDisabled: boolean) {
    setPending((p) => ({ ...p, [toolName]: true }))
    try {
      await api.toggleTool(toolName, nextDisabled)
      await qc.invalidateQueries({ queryKey: qk.tools })
      toast.success(nextDisabled ? `"${toolName}" disabled` : `"${toolName}" enabled`)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to toggle tool")
    } finally {
      setPending((p) => ({ ...p, [toolName]: false }))
    }
  }

  async function handleConfirm(toolName: string, nextRequire: boolean) {
    const key = toolName + "_conf"
    setPending((p) => ({ ...p, [key]: true }))
    try {
      await api.setToolConfirmation(toolName, nextRequire)
      await qc.invalidateQueries({ queryKey: qk.tools })
      toast.success(
        nextRequire
          ? `Confirmation required for "${toolName}"`
          : `Confirmation removed for "${toolName}"`,
      )
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to update confirmation setting")
    } finally {
      setPending((p) => ({ ...p, [key]: false }))
    }
  }

  // --- filtering ---

  const q = search.trim().toLowerCase()

  const matchesTool = (name: string, description: string) =>
    !q || name.toLowerCase().includes(q) || description.toLowerCase().includes(q)

  const filteredServerTools = (data?.server_tools ?? []).filter((t) =>
    matchesTool(t.name, t.description),
  )

  const filteredEdgeDevices = (data?.edge_devices ?? [])
    .map((dev) => ({
      ...dev,
      tools: dev.tools.filter((t) => matchesTool(t.name, t.description)),
    }))
    .filter(
      (dev) =>
        !q || dev.edge_name.toLowerCase().includes(q) || dev.tools.length > 0,
    )

  // --- summary counts (always from raw data) ---

  const totalServer = data?.server_tools.length ?? 0
  const enabledServer = (data?.server_tools ?? []).filter((t) => !t.disabled).length
  const disabledServer = totalServer - enabledServer
  const totalEdge = data?.edge_devices.length ?? 0
  const onlineEdge = (data?.edge_devices ?? []).filter((d) => d.online).length

  // --- header actions (shared across all states) ---

  const headerActions = (
    <>
      <Input
        placeholder="Search tools…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="h-8 w-44 text-sm"
      />
      <SimpleTooltip label="Refresh" side="bottom">
        <Button
          variant="outline"
          size="icon-sm"
          onClick={() => refetch()}
          disabled={isLoading}
          aria-label="Refresh tools"
        >
          <RefreshCw className={cn("size-4", isLoading && "animate-spin")} />
        </Button>
      </SimpleTooltip>
    </>
  )

  const pageHeaderProps = {
    title: "Tools",
    description: "Enable, disable, and gate the tools your agent can call.",
    icon: Wrench,
    actions: headerActions,
  } as const

  // --- loading ---

  if (isLoading) {
    return (
      <>
        <PageHeader {...pageHeaderProps} />
        <ToolsSkeleton />
      </>
    )
  }

  // --- error ---

  if (isError) {
    return (
      <>
        <PageHeader {...pageHeaderProps} />
        <PageBody>
          <div className="flex flex-col items-center gap-3 py-24 text-sm text-muted-foreground">
            <PackageSearch className="size-10 opacity-40" />
            <p>Failed to load tools. Make sure the Yumi server is running.</p>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              Try again
            </Button>
          </div>
        </PageBody>
      </>
    )
  }

  // --- main render ---

  const hasEdgeDevices = (data?.edge_devices ?? []).length > 0

  return (
    <>
      <PageHeader {...pageHeaderProps} />
      <PageBody>
        {/* Summary badges */}
        <div className="mb-6 flex flex-wrap gap-2">
          <Badge variant="outline">{totalServer} server tool{totalServer !== 1 ? "s" : ""}</Badge>
          <Badge variant="success">{enabledServer} enabled</Badge>
          {disabledServer > 0 && (
            <Badge variant="muted">{disabledServer} disabled</Badge>
          )}
          {hasEdgeDevices && (
            <>
              <Badge variant="outline">
                {totalEdge} edge device{totalEdge !== 1 ? "s" : ""}
              </Badge>
              <Badge variant={onlineEdge > 0 ? "success" : "muted"}>
                {onlineEdge}/{totalEdge} online
              </Badge>
            </>
          )}
        </div>

        {/* ── Server tools ── */}
        <section className="mb-8">
          <h2 className="mb-3 text-sm font-semibold tracking-tight">Server tools</h2>

          {filteredServerTools.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border py-12 text-sm text-muted-foreground">
              <PackageSearch className="size-8 opacity-40" />
              <p>
                {q
                  ? "No server tools match your search."
                  : "No server tools are configured."}
              </p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {filteredServerTools.map((tool) => (
                <ToolCard
                  key={tool.name}
                  name={tool.name}
                  description={tool.description}
                  disabled={tool.disabled}
                  requireConfirmation={tool.require_confirmation}
                  isPending={!!pending[tool.name]}
                  isConfirmPending={!!pending[tool.name + "_conf"]}
                  onToggle={(next) => handleToggle(tool.name, next)}
                  onConfirm={(next) => handleConfirm(tool.name, next)}
                />
              ))}
            </div>
          )}
        </section>

        {/* ── Edge devices ── */}
        {hasEdgeDevices && (
          <section>
            <h2 className="mb-3 text-sm font-semibold tracking-tight">Edge devices</h2>

            {filteredEdgeDevices.length === 0 ? (
              <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border py-12 text-sm text-muted-foreground">
                <Cpu className="size-8 opacity-40" />
                <p>No edge devices match your search.</p>
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                {filteredEdgeDevices.map((dev) => (
                  <EdgeDeviceCard
                    key={dev.edge_name}
                    device={dev}
                    pending={pending}
                    searchActive={!!q}
                    onToggle={handleToggle}
                    onConfirm={handleConfirm}
                  />
                ))}
              </div>
            )}
          </section>
        )}
      </PageBody>
    </>
  )
}
