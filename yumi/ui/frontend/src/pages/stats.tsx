import {
  BarChart3,
  RefreshCw,
  Zap,
  Wrench,
  MessageSquare,
  Activity,
  Layers,
} from "lucide-react"
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  AreaChart,
  Area,
  Legend,
} from "recharts"
import { toast } from "sonner"
import { useQueryClient } from "@tanstack/react-query"

import { PageHeader, PageBody } from "@/components/layout/page"
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useStats } from "@/hooks/queries"
import { qk } from "@/hooks/queries"
import { compact, withCommas, formatDuration, timeAgo } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { Stats } from "@/lib/types"

// ── palette ──────────────────────────────────────────────────────────────────
const CHART_COLORS = [
  "#7c5cff",
  "#22c55e",
  "#f59e0b",
  "#ef4444",
  "#38bdf8",
  "#e879f9",
]

const AXIS_STYLE = { stroke: "#88889a", fontSize: 12 }
const TOOLTIP_STYLE = {
  contentStyle: {
    background: "#1a1a2e",
    border: "1px solid #2a2a3e",
    borderRadius: 8,
    fontSize: 12,
  },
  labelStyle: { color: "#88889a" },
  itemStyle: { color: "#e5e7eb" },
}

// ── small StatCard ────────────────────────────────────────────────────────────
interface StatCardProps {
  icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }>
  label: string
  value: string
  sub?: string
  color?: string
}

function StatCard({ icon: Icon, label, value, sub, color }: StatCardProps) {
  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-center gap-2">
        <div
          className="flex size-8 items-center justify-center rounded-lg"
          style={{ background: `${color ?? "#7c5cff"}22` }}
        >
          <Icon
            className="size-4"
            style={{ color: color ?? "#7c5cff" }}
          />
        </div>
        <span className="text-sm font-medium text-muted-foreground">{label}</span>
      </div>
      <div>
        <p className="text-3xl font-semibold tracking-tight text-foreground">{value}</p>
        {sub && (
          <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>
        )}
      </div>
    </Card>
  )
}

// ── empty placeholder ─────────────────────────────────────────────────────────
function EmptyChart({ message }: { message: string }) {
  return (
    <div className="flex h-[240px] items-center justify-center">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  )
}

// ── chart: daily token usage ──────────────────────────────────────────────────
function DailyTokenChart({ data }: { data: Stats["tokens"]["daily"] }) {
  if (!data?.length) {
    return <EmptyChart message="No token usage recorded yet" />
  }

  const chartData = data.map((d) => ({
    day: d.day.slice(5), // MM-DD
    prompt: d.prompt_tokens,
    completion: d.completion_tokens,
  }))

  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="gradPrompt" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={CHART_COLORS[0]} stopOpacity={0.3} />
            <stop offset="95%" stopColor={CHART_COLORS[0]} stopOpacity={0} />
          </linearGradient>
          <linearGradient id="gradCompletion" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={CHART_COLORS[1]} stopOpacity={0.3} />
            <stop offset="95%" stopColor={CHART_COLORS[1]} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="day" {...AXIS_STYLE} tick={{ fill: "#88889a", fontSize: 12 }} axisLine={false} tickLine={false} />
        <YAxis {...AXIS_STYLE} tick={{ fill: "#88889a", fontSize: 12 }} axisLine={false} tickLine={false} tickFormatter={(v) => compact(v)} width={48} />
        <Tooltip {...TOOLTIP_STYLE} formatter={(v: number) => withCommas(v)} />
        <Legend wrapperStyle={{ fontSize: 12, color: "#88889a" }} />
        <Area
          type="monotone"
          dataKey="prompt"
          name="Prompt"
          stroke={CHART_COLORS[0]}
          strokeWidth={2}
          fill="url(#gradPrompt)"
          dot={false}
        />
        <Area
          type="monotone"
          dataKey="completion"
          name="Completion"
          stroke={CHART_COLORS[1]}
          strokeWidth={2}
          fill="url(#gradCompletion)"
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

// ── chart: tokens by model ────────────────────────────────────────────────────
function ModelTokenChart({ data }: { data: Stats["tokens"]["by_model"] }) {
  if (!data?.length) {
    return <EmptyChart message="No model usage data yet" />
  }

  const chartData = data.map((m) => ({
    model: m.model.length > 22 ? m.model.slice(0, 20) + "…" : m.model,
    tokens: m.total_tokens,
  }))

  return (
    <ResponsiveContainer width="100%" height={Math.max(240, chartData.length * 44)}>
      <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
        <XAxis
          type="number"
          {...AXIS_STYLE}
          tick={{ fill: "#88889a", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => compact(v)}
        />
        <YAxis
          type="category"
          dataKey="model"
          {...AXIS_STYLE}
          tick={{ fill: "#88889a", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          width={140}
        />
        <Tooltip {...TOOLTIP_STYLE} formatter={(v: number) => withCommas(v)} />
        <Bar dataKey="tokens" name="Tokens" radius={[0, 4, 4, 0]}>
          {chartData.map((_, i) => (
            <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// ── chart: tool calls by status (donut) ──────────────────────────────────────
function ToolStatusChart({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data ?? {}).filter(([, v]) => v > 0)
  if (!entries.length) {
    return <EmptyChart message="No tool call data yet" />
  }

  const chartData = entries.map(([status, count]) => ({ name: status, value: count }))
  const total = chartData.reduce((s, d) => s + d.value, 0)

  return (
    <div className="relative flex items-center justify-center">
      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            innerRadius={64}
            outerRadius={100}
            paddingAngle={3}
            dataKey="value"
          >
            {chartData.map((_, i) => (
              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} stroke="transparent" />
            ))}
          </Pie>
          <Tooltip {...TOOLTIP_STYLE} formatter={(v: number) => withCommas(v)} />
          <Legend
            wrapperStyle={{ fontSize: 12, color: "#88889a" }}
            formatter={(value) => <span style={{ color: "#88889a", fontSize: 12 }}>{value}</span>}
          />
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute flex flex-col items-center">
        <span className="text-xl font-semibold text-foreground">{withCommas(total)}</span>
        <span className="text-xs text-muted-foreground">total</span>
      </div>
    </div>
  )
}

// ── chart: top tools ──────────────────────────────────────────────────────────
function TopToolsChart({ data }: { data: Stats["tool_calls"]["top_tools"] }) {
  if (!data?.length) {
    return <EmptyChart message="No tool usage data yet" />
  }

  const chartData = [...data]
    .sort((a, b) => b.count - a.count)
    .slice(0, 10)
    .map((t) => ({
      name: t.name.length > 26 ? t.name.slice(0, 24) + "…" : t.name,
      count: t.count,
    }))

  return (
    <ResponsiveContainer width="100%" height={Math.max(240, chartData.length * 40)}>
      <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
        <XAxis
          type="number"
          {...AXIS_STYLE}
          tick={{ fill: "#88889a", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          type="category"
          dataKey="name"
          {...AXIS_STYLE}
          tick={{ fill: "#88889a", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          width={150}
        />
        <Tooltip {...TOOLTIP_STYLE} formatter={(v: number) => withCommas(v)} />
        <Bar dataKey="count" name="Calls" radius={[0, 4, 4, 0]} fill={CHART_COLORS[0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

// ── loading skeletons ─────────────────────────────────────────────────────────
function LoadingSkeletons() {
  return (
    <>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Card key={i} className="p-5">
            <Skeleton className="mb-3 h-8 w-8 rounded-lg" />
            <Skeleton className="mb-2 h-8 w-24" />
            <Skeleton className="h-3 w-32" />
          </Card>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-5 w-40" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-[240px] w-full rounded-lg" />
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  )
}

// ── main page ─────────────────────────────────────────────────────────────────
export function StatsPage() {
  const { data: stats, isLoading, isError, refetch } = useStats(15000)
  const qc = useQueryClient()

  async function handleRefresh() {
    try {
      await refetch()
      qc.invalidateQueries({ queryKey: qk.stats })
    } catch {
      toast.error("Failed to refresh stats")
    }
  }

  const generatedAt = stats?.generated_at

  return (
    <>
      <PageHeader
        title="Statistics"
        description="Usage across tools, tokens, and conversations."
        icon={BarChart3}
        actions={
          <div className="flex items-center gap-3">
            {generatedAt && (
              <span className="text-xs text-muted-foreground">
                Updated {timeAgo(generatedAt)}
              </span>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={isLoading}
              className="gap-1.5"
            >
              <RefreshCw className={cn("size-3.5", isLoading && "animate-spin")} />
              Refresh
            </Button>
          </div>
        }
      />

      <PageBody>
        <div className="flex flex-col gap-6">
          {isLoading && <LoadingSkeletons />}

          {isError && !isLoading && (
            <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
              <Activity className="size-10 text-muted-foreground/50" />
              <p className="text-sm text-muted-foreground">
                Could not load statistics. Is the Yumi server running?
              </p>
              <Button variant="outline" size="sm" onClick={handleRefresh}>
                Try again
              </Button>
            </div>
          )}

          {stats && (
            <>
              {/* ── stat cards ─────────────────────────────────────────── */}
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
                <StatCard
                  icon={Zap}
                  label="Total tokens"
                  value={compact(stats.tokens.total)}
                  sub={`${compact(stats.tokens.prompt)} prompt / ${compact(stats.tokens.completion)} completion`}
                  color="#7c5cff"
                />
                <StatCard
                  icon={Wrench}
                  label="Tool calls"
                  value={withCommas(stats.tool_calls.total)}
                  sub={
                    stats.tool_calls.avg_duration_ms
                      ? `avg ${formatDuration(stats.tool_calls.avg_duration_ms)}`
                      : undefined
                  }
                  color="#22c55e"
                />
                <StatCard
                  icon={MessageSquare}
                  label="Conv. turns"
                  value={withCommas(stats.sessions.total_turns)}
                  sub={`${withCommas(stats.sessions.total_messages)} messages total`}
                  color="#f59e0b"
                />
                <StatCard
                  icon={Activity}
                  label="Active sessions"
                  value={withCommas(stats.sessions.active)}
                  sub={
                    stats.sessions.avg_messages
                      ? `avg ${compact(stats.sessions.avg_messages)} msgs/session`
                      : undefined
                  }
                  color="#38bdf8"
                />
                <StatCard
                  icon={Layers}
                  label="Tools available"
                  value={withCommas(stats.tools.total)}
                  sub={`${stats.tools.edge_online}/${stats.tools.edge_devices} edge online`}
                  color="#e879f9"
                />
              </div>

              {/* ── charts ─────────────────────────────────────────────── */}
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {/* Daily token usage */}
                <Card className="md:col-span-2">
                  <CardHeader>
                    <CardTitle>Token usage (14 days)</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <DailyTokenChart data={stats.tokens.daily} />
                  </CardContent>
                </Card>

                {/* Tokens by model */}
                <Card>
                  <CardHeader>
                    <CardTitle>Tokens by model</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <ModelTokenChart data={stats.tokens.by_model} />
                  </CardContent>
                </Card>

                {/* Tool calls by status */}
                <Card>
                  <CardHeader>
                    <CardTitle>Tool calls by status</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <ToolStatusChart data={stats.tool_calls.by_status} />
                  </CardContent>
                </Card>

                {/* Top tools */}
                <Card className="md:col-span-2">
                  <CardHeader>
                    <CardTitle>Top tools</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <TopToolsChart data={stats.tool_calls.top_tools} />
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </div>
      </PageBody>
    </>
  )
}
