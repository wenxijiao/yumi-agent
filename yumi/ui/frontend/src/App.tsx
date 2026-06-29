import { useEffect } from "react"
import { Route, Routes } from "react-router-dom"
import { AppShell } from "@/components/layout/app-shell"
import { ChatPage } from "@/pages/chat"
import { ToolsPage } from "@/pages/tools"
import { StatsPage } from "@/pages/stats"
import { SettingsPage } from "@/pages/settings"
import { TimersPage } from "@/pages/timers"
import { MemoryPage } from "@/pages/memory"
import { SetupWizard } from "@/pages/setup"
import { useTheme } from "@/hooks/use-theme"

export default function App() {
  const hydrate = useTheme((s) => s.hydrate)
  useEffect(() => {
    hydrate()
  }, [hydrate])

  return (
    <Routes>
      <Route path="/setup" element={<SetupWizard />} />
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
  )
}
