import { Suspense, lazy, useEffect } from "react"
import { Route, Routes, useLocation, useNavigate } from "react-router-dom"
import { AppShell } from "@/components/layout/app-shell"
import { ChatPage } from "@/pages/chat"
import { useTheme } from "@/hooks/use-theme"
import { useModelConfig } from "@/hooks/queries"

// Code-split the non-chat pages (recharts, forms, etc.) out of the initial chat load.
const ToolsPage = lazy(() => import("@/pages/tools").then((m) => ({ default: m.ToolsPage })))
const StatsPage = lazy(() => import("@/pages/stats").then((m) => ({ default: m.StatsPage })))
const SettingsPage = lazy(() => import("@/pages/settings").then((m) => ({ default: m.SettingsPage })))
const TimersPage = lazy(() => import("@/pages/timers").then((m) => ({ default: m.TimersPage })))
const MemoryPage = lazy(() => import("@/pages/memory").then((m) => ({ default: m.MemoryPage })))
const SetupWizard = lazy(() => import("@/pages/setup").then((m) => ({ default: m.SetupWizard })))

function PageFallback() {
  return <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">Loading…</div>
}

/** Send a never-configured user to the setup wizard on first load. */
function FirstRunGate() {
  const { data, isSuccess } = useModelConfig()
  const navigate = useNavigate()
  const location = useLocation()
  useEffect(() => {
    if (isSuccess && data && !(data.chat_model || "").trim() && location.pathname !== "/setup") {
      navigate("/setup", { replace: true })
    }
  }, [isSuccess, data, location.pathname, navigate])
  return null
}

export default function App() {
  const hydrate = useTheme((s) => s.hydrate)
  useEffect(() => {
    hydrate()
  }, [hydrate])

  return (
    <>
      <FirstRunGate />
      <Routes>
        <Route
          path="/setup"
          element={
            <Suspense fallback={<PageFallback />}>
              <SetupWizard />
            </Suspense>
          }
        />
        <Route element={<AppShell />}>
          <Route path="/" element={<ChatPage />} />
          <Route path="/tools" element={<ToolsPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="/timers" element={<TimersPage />} />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<ChatPage />} />
        </Route>
      </Routes>
    </>
  )
}
