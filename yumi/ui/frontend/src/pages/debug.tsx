import type { ReactNode } from "react"
import { AlertTriangle, CheckCircle2, Info, RefreshCw, Stethoscope } from "lucide-react"
import { PageBody, PageHeader } from "@/components/layout/page"
import { Button } from "@/components/ui/button"
import { useObservability } from "@/hooks/queries"
import { cn } from "@/lib/utils"
import type { ObservabilityDiagnosis, ObservabilityEdge, RoutingTrace, Trace } from "@/lib/types"

function fmtTime(ts?: string): string {
  if (!ts) return "—"
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleTimeString()
}

const DIAG_STYLE: Record<ObservabilityDiagnosis["level"], { cls: string; Icon: typeof Info }> = {
  ok: { cls: "border-success/30 bg-success/10 text-success", Icon: CheckCircle2 },
  warning: { cls: "border-destructive/30 bg-destructive/10 text-destructive", Icon: AlertTriangle },
  info: { cls: "border-border bg-muted/40 text-muted-foreground", Icon: Info },
}

function DiagnosisBanner({ diag }: { diag: ObservabilityDiagnosis }) {
  const { cls, Icon } = DIAG_STYLE[diag.level] ?? DIAG_STYLE.info
  return (
    <div className={cn("flex items-start gap-3 rounded-xl border px-4 py-3 text-sm", cls)}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <p className="leading-relaxed">{diag.message}</p>
    </div>
  )
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
      </div>
      {children}
    </section>
  )
}

function Chip({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "warn" }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn("text-sm font-medium", tone === "warn" && "text-destructive")}>{value}</div>
    </div>
  )
}

function StatusDot({ online }: { online: boolean }) {
  return (
    <span
      className={cn("inline-block size-2 rounded-full", online ? "bg-success" : "bg-muted-foreground/40")}
      title={online ? "online" : "offline"}
    />
  )
}

function EdgeCard({ edge }: { edge: ObservabilityEdge }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <StatusDot online={edge.online} />
        <span className="font-medium">{edge.edge_name}</span>
        <span className="ml-auto text-xs text-muted-foreground">{edge.tool_count} tool(s)</span>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        owner: <span className="font-mono">{edge.owner_user_id ?? "—"}</span>
      </div>
      <ul className="mt-3 space-y-1">
        {edge.tools.map((t) => (
          <li key={t.full_name} className="flex items-center gap-2 text-sm">
            <span className="font-mono text-xs">{t.name}</span>
            {t.always_include && (
              <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">pinned</span>
            )}
            {t.require_confirmation && (
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">confirm</span>
            )}
          </li>
        ))}
        {edge.tools.length === 0 && <li className="text-xs text-muted-foreground">no tools mounted</li>}
      </ul>
    </div>
  )
}

function routingRowTone(t: RoutingTrace): string {
  const total = t.total_edge_count ?? 0
  const selected = t.selected_edge_count ?? 0
  if (total === 0) return "text-destructive"
  if (selected === 0) return "text-amber-500 dark:text-amber-400"
  return ""
}

export function DebugPage() {
  const { data, isLoading, isError, error, refetch, isFetching } = useObservability(8000)

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Debug"
        description={data ? `Chatting as ${data.identity.user_id ?? "—"}` : "Edge & tool-routing observability"}
        icon={Stethoscope}
        actions={
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={cn("mr-1.5 size-4", isFetching && "animate-spin")} />
            Refresh
          </Button>
        }
      />
      <PageBody className="space-y-6">
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {isError && (
          <p className="text-sm text-destructive">
            Failed to load: {String((error as Error)?.message ?? error)}
          </p>
        )}

        {data && (
          <>
            {/* Auto-diagnosis */}
            <div className="space-y-2">
              {data.diagnosis.map((d, i) => (
                <DiagnosisBanner key={i} diag={d} />
              ))}
            </div>

            {/* Routing config */}
            <Section title="Routing config" hint="how edge tools are exposed to the model">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Chip label="Dynamic routing" value={data.config.dynamic_routing_enabled ? "on" : "off"} />
                <Chip
                  label="Retrieval limit"
                  value={String(data.config.edge_tools_retrieval_limit ?? "—")}
                  tone={data.config.edge_tools_retrieval_limit === 0 ? "warn" : "default"}
                />
                <Chip label="Always-expose below" value={String(data.config.edge_tools_always_expose_below ?? "—")} />
                <Chip
                  label="Embedding model"
                  value={data.config.embedding_model_set ? "set" : "unset"}
                  tone={data.config.embedding_model_set ? "default" : "warn"}
                />
              </div>
            </Section>

            {/* Connected edges */}
            <Section title="Connected edges" hint={`${data.edges.length} device(s)`}>
              {data.edges.length === 0 ? (
                <p className="text-sm text-muted-foreground">No edge devices are connected.</p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  {data.edges.map((e) => (
                    <EdgeCard key={e.connection_key} edge={e} />
                  ))}
                </div>
              )}
            </Section>

            {/* Tool routing decisions */}
            <Section title="Tool routing (per chat turn)" hint="visible vs selected edge tools each turn">
              {data.routing_traces.length === 0 ? (
                <p className="text-sm text-muted-foreground">No routing decisions recorded yet.</p>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-border">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40 text-xs text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Time</th>
                        <th className="px-3 py-2 text-left font-medium">Query</th>
                        <th className="px-3 py-2 text-right font-medium">Visible</th>
                        <th className="px-3 py-2 text-right font-medium">Selected</th>
                        <th className="px-3 py-2 text-left font-medium">Tools</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.routing_traces.map((t, i) => (
                        <tr key={t.id ?? i} className="border-t border-border">
                          <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">
                            {fmtTime(t.ts)}
                          </td>
                          <td className="max-w-[260px] truncate px-3 py-2" title={t.query_preview}>
                            {t.query_preview || "—"}
                          </td>
                          <td className={cn("px-3 py-2 text-right tabular-nums", routingRowTone(t))}>
                            {t.total_edge_count ?? 0}
                          </td>
                          <td className={cn("px-3 py-2 text-right tabular-nums", routingRowTone(t))}>
                            {t.selected_edge_count ?? 0}
                          </td>
                          <td className="max-w-[260px] truncate px-3 py-2 font-mono text-xs text-muted-foreground">
                            {(t.selected_edge_tools ?? []).join(", ") || "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>

            {/* Tool calls */}
            <Section title="Recent tool calls" hint={`${data.tool_calls.length} call(s)`}>
              {data.tool_calls.length === 0 ? (
                <p className="text-sm text-muted-foreground">No tool calls recorded yet.</p>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-border">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40 text-xs text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Time</th>
                        <th className="px-3 py-2 text-left font-medium">Tool</th>
                        <th className="px-3 py-2 text-left font-medium">Edge</th>
                        <th className="px-3 py-2 text-left font-medium">Status</th>
                        <th className="px-3 py-2 text-right font-medium">ms</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.tool_calls.map((t: Trace, i) => (
                        <tr key={t.id ?? i} className="border-t border-border">
                          <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">
                            {fmtTime(t.ts)}
                          </td>
                          <td className="px-3 py-2 font-mono text-xs">{t.display_name || t.tool_name}</td>
                          <td className="px-3 py-2 text-xs text-muted-foreground">{t.edge_name || "—"}</td>
                          <td
                            className={cn(
                              "px-3 py-2 text-xs",
                              t.status === "error" && "text-destructive",
                              t.status === "success" && "text-success",
                            )}
                          >
                            {t.status}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-xs text-muted-foreground">
                            {t.duration_ms}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>
          </>
        )}
      </PageBody>
    </div>
  )
}
