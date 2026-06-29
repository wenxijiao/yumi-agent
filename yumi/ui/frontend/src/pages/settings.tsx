import { useState, useEffect, type ReactNode } from "react"
import {
  Settings,
  Moon,
  Sun,
  Volume2,
  Loader2,
  BrainCircuit,
  Check,
  FileText,
  Mic,
  Palette,
  SlidersHorizontal,
} from "lucide-react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { PageHeader, PageBody } from "@/components/layout/page"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { Slider } from "@/components/ui/slider"
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import { api, synthesizeSpeech } from "@/lib/api"
import { useModelConfig, useSystemPrompt, qk } from "@/hooks/queries"
import { useApp } from "@/store/app"
import { useTheme } from "@/hooks/use-theme"

// ── helpers ──────────────────────────────────────────────────────────────────

function FieldRow({ children }: { children: ReactNode }) {
  return <div className="space-y-2">{children}</div>
}

function SectionSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-8 w-48 rounded-lg" />
      <Skeleton className="h-32 w-full rounded-xl" />
    </div>
  )
}

// ── SettingsPage ──────────────────────────────────────────────────────────────

export function SettingsPage() {
  const qc = useQueryClient()
  const { data: modelConfig, isLoading: configLoading } = useModelConfig()
  const { data: promptData, isLoading: promptLoading } = useSystemPrompt()
  const voiceReplies = useApp((s) => s.voiceReplies)
  const setVoiceReplies = useApp((s) => s.setVoiceReplies)
  const { theme, setTheme } = useTheme()

  // ── Models form ──────────────────────────────────────────────────────────
  const [chatProvider, setChatProvider] = useState("")
  const [chatModel, setChatModel] = useState("")
  const [embeddingProvider, setEmbeddingProvider] = useState("")
  const [embeddingModel, setEmbeddingModel] = useState("")
  const [openaiKey, setOpenaiKey] = useState("")
  const [geminiKey, setGeminiKey] = useState("")
  const [claudeKey, setClaudeKey] = useState("")
  const [deepseekKey, setDeepseekKey] = useState("")
  const [grokKey, setGrokKey] = useState("")
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState("")
  const [deepseekBaseUrl, setDeepseekBaseUrl] = useState("")
  const [grokBaseUrl, setGrokBaseUrl] = useState("")
  const [modelsSaving, setModelsSaving] = useState(false)
  const [savingKey, setSavingKey] = useState<string | null>(null)

  // ── Prompts form ─────────────────────────────────────────────────────────
  const [systemPromptText, setSystemPromptText] = useState("")
  const [promptSaving, setPromptSaving] = useState(false)

  // ── Memory form ──────────────────────────────────────────────────────────
  const [maxRecentMessages, setMaxRecentMessages] = useState(30)
  const [maxRelatedMessages, setMaxRelatedMessages] = useState(15)
  const [memorySaving, setMemorySaving] = useState(false)

  // ── Voice form ───────────────────────────────────────────────────────────
  const [sttProvider, setSttProvider] = useState("")
  const [sttModel, setSttModel] = useState("")
  const [sttLanguage, setSttLanguage] = useState("")
  const [ttsProvider, setTtsProvider] = useState("")
  const [ttsVoice, setTtsVoice] = useState("")
  const [ttsModel, setTtsModel] = useState("")
  const [ttsLanguage, setTtsLanguage] = useState("")
  const [dashscopeKey, setDashscopeKey] = useState("")
  const [voiceSaving, setVoiceSaving] = useState(false)
  const [testingVoice, setTestingVoice] = useState(false)

  // ── Advanced form ────────────────────────────────────────────────────────
  const [dynamicRouting, setDynamicRouting] = useState(false)
  const [retrievalLimit, setRetrievalLimit] = useState(50)
  const [advancedSaving, setAdvancedSaving] = useState(false)

  // ── Sync from server data ────────────────────────────────────────────────
  useEffect(() => {
    if (!modelConfig) return
    setChatProvider(modelConfig.chat_provider ?? "")
    setChatModel(modelConfig.chat_model ?? "")
    setEmbeddingProvider(modelConfig.embedding_provider ?? "")
    setEmbeddingModel(modelConfig.embedding_model ?? "")
    setOpenaiBaseUrl(modelConfig.openai_base_url ?? "")
    setDeepseekBaseUrl(modelConfig.deepseek_base_url ?? "")
    setGrokBaseUrl(modelConfig.grok_base_url ?? "")
    setMaxRecentMessages(modelConfig.memory_max_recent_messages ?? 30)
    setMaxRelatedMessages(modelConfig.memory_max_related_messages ?? 15)
    setSttProvider(modelConfig.stt_provider ?? "")
    setSttModel(modelConfig.stt_model ?? "")
    setSttLanguage(modelConfig.stt_language ?? "")
    setTtsProvider(modelConfig.tts_provider ?? "")
    setTtsVoice(modelConfig.tts_voice ?? "")
    setTtsModel(modelConfig.tts_model ?? "")
    setTtsLanguage(modelConfig.tts_language ?? "")
    setDynamicRouting(modelConfig.edge_tools_enable_dynamic_routing ?? false)
    setRetrievalLimit(modelConfig.edge_tools_retrieval_limit ?? 50)
  }, [modelConfig])

  useEffect(() => {
    if (!promptData) return
    setSystemPromptText(promptData.system_prompt ?? "")
  }, [promptData])

  // ── Handlers ─────────────────────────────────────────────────────────────

  async function saveModels() {
    setModelsSaving(true)
    try {
      const patch: Record<string, unknown> = {}
      if (chatProvider !== (modelConfig?.chat_provider ?? "")) patch.chat_provider = chatProvider
      if (chatModel !== (modelConfig?.chat_model ?? "")) patch.chat_model = chatModel
      if (embeddingProvider !== (modelConfig?.embedding_provider ?? "")) patch.embedding_provider = embeddingProvider
      if (embeddingModel !== (modelConfig?.embedding_model ?? "")) patch.embedding_model = embeddingModel
      if (openaiKey) patch.openai_api_key = openaiKey
      if (geminiKey) patch.gemini_api_key = geminiKey
      if (claudeKey) patch.claude_api_key = claudeKey
      if (deepseekKey) patch.deepseek_api_key = deepseekKey
      if (grokKey) patch.grok_api_key = grokKey
      if (openaiBaseUrl !== (modelConfig?.openai_base_url ?? "")) patch.openai_base_url = openaiBaseUrl
      if (deepseekBaseUrl !== (modelConfig?.deepseek_base_url ?? "")) patch.deepseek_base_url = deepseekBaseUrl
      if (grokBaseUrl !== (modelConfig?.grok_base_url ?? "")) patch.grok_base_url = grokBaseUrl
      await api.updateModelConfig(patch)
      await qc.invalidateQueries({ queryKey: qk.modelConfig })
      // Clear key fields after successful save
      setOpenaiKey("")
      setGeminiKey("")
      setClaudeKey("")
      setDeepseekKey("")
      setGrokKey("")
      toast.success("Model settings saved")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save model settings")
    } finally {
      setModelsSaving(false)
    }
  }

  async function saveKey(field: string, value: string, clear: () => void) {
    const v = value.trim()
    if (!v) return
    setSavingKey(field)
    try {
      await api.updateModelConfig({ [field]: v })
      await qc.invalidateQueries({ queryKey: qk.modelConfig })
      clear()
      toast.success("API key saved")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save API key")
    } finally {
      setSavingKey(null)
    }
  }

  async function savePrompt() {
    setPromptSaving(true)
    try {
      await api.setSystemPrompt(systemPromptText)
      await qc.invalidateQueries({ queryKey: qk.systemPrompt })
      toast.success("System prompt saved")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save system prompt")
    } finally {
      setPromptSaving(false)
    }
  }

  async function resetPrompt() {
    setPromptSaving(true)
    try {
      await api.resetSystemPrompt()
      await qc.invalidateQueries({ queryKey: qk.systemPrompt })
      toast.success("System prompt reset to default")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to reset system prompt")
    } finally {
      setPromptSaving(false)
    }
  }

  async function saveMemory() {
    setMemorySaving(true)
    try {
      await api.updateModelConfig({
        memory_max_recent_messages: maxRecentMessages,
        memory_max_related_messages: maxRelatedMessages,
      })
      await qc.invalidateQueries({ queryKey: qk.modelConfig })
      toast.success("Memory settings saved")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save memory settings")
    } finally {
      setMemorySaving(false)
    }
  }

  function voicePatch(): Record<string, unknown> {
    const patch: Record<string, unknown> = {
      stt_provider: sttProvider,
      stt_model: sttModel,
      stt_language: sttLanguage,
      tts_provider: ttsProvider,
      tts_voice: ttsVoice,
      tts_model: ttsModel,
      tts_language: ttsLanguage,
    }
    if (dashscopeKey.trim()) patch.tts_api_key = dashscopeKey.trim()
    return patch
  }

  async function saveVoice() {
    setVoiceSaving(true)
    try {
      await api.updateModelConfig(voicePatch())
      await qc.invalidateQueries({ queryKey: qk.modelConfig })
      setDashscopeKey("")
      toast.success("Voice settings saved")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save voice settings")
    } finally {
      setVoiceSaving(false)
    }
  }

  async function testVoice() {
    setTestingVoice(true)
    try {
      // Persist the current form first so the test uses the selection on screen,
      // not whatever was last saved.
      await api.updateModelConfig(voicePatch())
      await qc.invalidateQueries({ queryKey: qk.modelConfig })
      setDashscopeKey("")
      const url = await synthesizeSpeech("Hello, this is Yumi.")
      const audio = new Audio(url)
      audio.onended = () => URL.revokeObjectURL(url)
      await audio.play().catch(() => {
        URL.revokeObjectURL(url)
        toast.error("Your browser blocked audio playback.")
      })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Voice test failed")
    } finally {
      setTestingVoice(false)
    }
  }

  async function saveAdvanced() {
    setAdvancedSaving(true)
    try {
      await api.updateModelConfig({
        edge_tools_enable_dynamic_routing: dynamicRouting,
        edge_tools_retrieval_limit: retrievalLimit,
      })
      await qc.invalidateQueries({ queryKey: qk.modelConfig })
      toast.success("Advanced settings saved")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save advanced settings")
    } finally {
      setAdvancedSaving(false)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="Settings"
        icon={Settings}
        description="Configure the Yumi agent — models, prompts, voice, and more"
      />
      <PageBody>
        <Tabs defaultValue="models" className="space-y-0">
          <TabsList className="mb-6 flex h-auto flex-wrap gap-1 bg-muted/40 p-1">
            <TabsTrigger value="models" className="gap-1.5">
              <BrainCircuit className="size-3.5" />
              Models
            </TabsTrigger>
            <TabsTrigger value="prompts" className="gap-1.5">
              <FileText className="size-3.5" />
              Prompts
            </TabsTrigger>
            <TabsTrigger value="memory" className="gap-1.5">
              <BrainCircuit className="size-3.5" />
              Memory
            </TabsTrigger>
            <TabsTrigger value="voice" className="gap-1.5">
              <Mic className="size-3.5" />
              Voice
            </TabsTrigger>
            <TabsTrigger value="appearance" className="gap-1.5">
              <Palette className="size-3.5" />
              Appearance
            </TabsTrigger>
            <TabsTrigger value="advanced" className="gap-1.5">
              <SlidersHorizontal className="size-3.5" />
              Advanced
            </TabsTrigger>
          </TabsList>

          {/* ── MODELS ─────────────────────────────────────────────────────── */}
          <TabsContent value="models" className="space-y-4">
            {configLoading ? (
              <div className="space-y-4">
                <SectionSkeleton />
                <SectionSkeleton />
                <SectionSkeleton />
              </div>
            ) : (
              <>
                {/* Chat model */}
                <Card>
                  <CardHeader>
                    <CardTitle>Chat Model</CardTitle>
                    <CardDescription>The LLM used for generating responses</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid gap-4 sm:grid-cols-2">
                      <FieldRow>
                        <Label>Provider</Label>
                        <Select value={chatProvider} onValueChange={setChatProvider}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select provider" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="ollama">Ollama</SelectItem>
                            <SelectItem value="openai">OpenAI</SelectItem>
                            <SelectItem value="gemini">Gemini</SelectItem>
                            <SelectItem value="claude">Claude</SelectItem>
                            <SelectItem value="deepseek">DeepSeek</SelectItem>
                            <SelectItem value="grok">Grok</SelectItem>
                          </SelectContent>
                        </Select>
                      </FieldRow>
                      <FieldRow>
                        <Label>Model name</Label>
                        <Input
                          value={chatModel}
                          onChange={(e) => setChatModel(e.target.value)}
                          placeholder="e.g. gpt-4o, gemma3:12b, claude-opus-4-5"
                        />
                      </FieldRow>
                    </div>
                  </CardContent>
                </Card>

                {/* Embedding model */}
                <Card>
                  <CardHeader>
                    <CardTitle>Embedding Model</CardTitle>
                    <CardDescription>Used for semantic memory and search recall</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <FieldRow>
                        <Label>Provider</Label>
                        <Select value={embeddingProvider} onValueChange={setEmbeddingProvider}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select provider" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="openai">OpenAI</SelectItem>
                            <SelectItem value="gemini">Gemini</SelectItem>
                            <SelectItem value="fastembed">FastEmbed (local)</SelectItem>
                            <SelectItem value="ollama">Ollama</SelectItem>
                            <SelectItem value="disabled">Disabled</SelectItem>
                          </SelectContent>
                        </Select>
                      </FieldRow>
                      <FieldRow>
                        <Label>Model name</Label>
                        <Input
                          value={embeddingModel}
                          onChange={(e) => setEmbeddingModel(e.target.value)}
                          placeholder="e.g. text-embedding-3-small"
                        />
                      </FieldRow>
                    </div>
                  </CardContent>
                </Card>

                {/* API keys */}
                <Card>
                  <CardHeader>
                    <CardTitle>API Keys</CardTitle>
                    <CardDescription>
                      Keys are stored server-side and never returned in full. Paste a key and press{" "}
                      <span className="font-medium text-foreground">Save</span> (or Enter) to store it.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {(
                      [
                        { label: "OpenAI", id: "openai", field: "openai_api_key", value: openaiKey, setter: setOpenaiKey, saved: modelConfig?.openai_api_key_saved },
                        { label: "Gemini", id: "gemini", field: "gemini_api_key", value: geminiKey, setter: setGeminiKey, saved: modelConfig?.gemini_api_key_saved },
                        { label: "Claude (Anthropic)", id: "claude", field: "claude_api_key", value: claudeKey, setter: setClaudeKey, saved: modelConfig?.claude_api_key_saved },
                        { label: "DeepSeek", id: "deepseek", field: "deepseek_api_key", value: deepseekKey, setter: setDeepseekKey, saved: modelConfig?.deepseek_api_key_saved },
                        { label: "Grok (xAI)", id: "grok", field: "grok_api_key", value: grokKey, setter: setGrokKey, saved: modelConfig?.grok_api_key_saved },
                      ] as const
                    ).map(({ label, id, field, value, setter, saved }) => {
                      const dirty = value.trim().length > 0
                      return (
                        <div key={id} className="flex items-center gap-3">
                          <span className="w-36 shrink-0 text-sm font-medium text-muted-foreground">{label}</span>
                          <Input
                            type="password"
                            value={value}
                            onChange={(e) => setter(e.target.value as string)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                                e.preventDefault()
                                saveKey(field, value, () => setter(""))
                              }
                            }}
                            placeholder={saved ? "•••••••••••  saved — paste a new key to replace" : "Paste API key to set"}
                            className="flex-1"
                          />
                          {dirty ? (
                            <Button
                              size="sm"
                              className="w-20 shrink-0"
                              onClick={() => saveKey(field, value, () => setter(""))}
                              disabled={savingKey === field}
                            >
                              {savingKey === field ? <Loader2 className="size-4 animate-spin" /> : "Save"}
                            </Button>
                          ) : saved ? (
                            <Badge variant="success" className="w-20 shrink-0 justify-center">
                              <Check className="size-3" />
                              Saved
                            </Badge>
                          ) : (
                            <Badge variant="muted" className="w-20 shrink-0 justify-center">
                              Not set
                            </Badge>
                          )}
                        </div>
                      )
                    })}
                  </CardContent>
                </Card>

                {/* Base URLs */}
                <Card>
                  <CardHeader>
                    <CardTitle>Base URLs</CardTitle>
                    <CardDescription>Override API endpoint base URLs (leave blank to use provider defaults)</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <FieldRow>
                      <Label>OpenAI base URL</Label>
                      <Input
                        value={openaiBaseUrl}
                        onChange={(e) => setOpenaiBaseUrl(e.target.value)}
                        placeholder="https://api.openai.com/v1"
                      />
                    </FieldRow>
                    <FieldRow>
                      <Label>DeepSeek base URL</Label>
                      <Input
                        value={deepseekBaseUrl}
                        onChange={(e) => setDeepseekBaseUrl(e.target.value)}
                        placeholder="https://api.deepseek.com"
                      />
                    </FieldRow>
                    <FieldRow>
                      <Label>Grok base URL</Label>
                      <Input
                        value={grokBaseUrl}
                        onChange={(e) => setGrokBaseUrl(e.target.value)}
                        placeholder="https://api.x.ai/v1"
                      />
                    </FieldRow>
                  </CardContent>
                </Card>

                <div className="flex justify-end">
                  <Button onClick={saveModels} disabled={modelsSaving}>
                    {modelsSaving && <Loader2 className="mr-2 size-4 animate-spin" />}
                    Save model settings
                  </Button>
                </div>
              </>
            )}
          </TabsContent>

          {/* ── PROMPTS ────────────────────────────────────────────────────── */}
          <TabsContent value="prompts" className="space-y-4">
            {promptLoading ? (
              <SectionSkeleton />
            ) : (
              <Card>
                <CardHeader>
                  <CardTitle>System Prompt</CardTitle>
                  <CardDescription>
                    Injected at the start of every conversation to shape Yumi&apos;s behavior.
                    {promptData?.is_default && (
                      <span className="ml-1 italic text-muted-foreground">
                        Currently using the built-in default prompt.
                      </span>
                    )}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <Textarea
                    value={systemPromptText}
                    onChange={(e) => setSystemPromptText(e.target.value)}
                    rows={18}
                    className="resize-y font-mono text-sm"
                    placeholder="Enter a system prompt…"
                  />
                  <div className="flex items-center justify-end gap-2">
                    <Button variant="outline" onClick={resetPrompt} disabled={promptSaving}>
                      Reset to default
                    </Button>
                    <Button onClick={savePrompt} disabled={promptSaving}>
                      {promptSaving && <Loader2 className="mr-2 size-4 animate-spin" />}
                      Save prompt
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* ── MEMORY ─────────────────────────────────────────────────────── */}
          <TabsContent value="memory" className="space-y-4">
            {configLoading ? (
              <SectionSkeleton />
            ) : (
              <Card>
                <CardHeader>
                  <CardTitle>Memory Settings</CardTitle>
                  <CardDescription>
                    Control how much conversation history is included in each LLM context window
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-8">
                  {/* Recent messages */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium">Recent messages</p>
                        <p className="text-xs text-muted-foreground">
                          Most recent turns always included in context
                        </p>
                      </div>
                      <span className="rounded-md bg-primary/10 px-2 py-0.5 text-sm font-semibold tabular-nums text-primary">
                        {maxRecentMessages}
                      </span>
                    </div>
                    <Slider
                      value={[maxRecentMessages]}
                      onValueChange={([v]) => setMaxRecentMessages(v)}
                      min={1}
                      max={200}
                      step={1}
                    />
                    <p className="text-xs text-muted-foreground">Range: 1–200</p>
                  </div>

                  <Separator />

                  {/* Related messages */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium">Semantic recall messages</p>
                        <p className="text-xs text-muted-foreground">
                          Additional semantically-related messages retrieved from history
                        </p>
                      </div>
                      <span className="rounded-md bg-primary/10 px-2 py-0.5 text-sm font-semibold tabular-nums text-primary">
                        {maxRelatedMessages}
                      </span>
                    </div>
                    <Slider
                      value={[maxRelatedMessages]}
                      onValueChange={([v]) => setMaxRelatedMessages(v)}
                      min={0}
                      max={50}
                      step={1}
                    />
                    <p className="text-xs text-muted-foreground">Range: 0–50 (0 = disabled)</p>
                  </div>

                  <div className="flex justify-end">
                    <Button onClick={saveMemory} disabled={memorySaving}>
                      {memorySaving && <Loader2 className="mr-2 size-4 animate-spin" />}
                      Save memory settings
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* ── VOICE ──────────────────────────────────────────────────────── */}
          <TabsContent value="voice" className="space-y-4">
            {configLoading ? (
              <div className="space-y-4">
                <SectionSkeleton />
                <SectionSkeleton />
              </div>
            ) : (
              <>
                {/* Auto-play toggle */}
                <Card>
                  <CardHeader>
                    <CardTitle>Spoken Replies</CardTitle>
                    <CardDescription>Auto-play TTS audio after each assistant response</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <p className="text-sm font-medium">Enable spoken replies</p>
                        <p className="text-xs text-muted-foreground">
                          Requires a TTS provider configured below
                        </p>
                      </div>
                      <Switch
                        checked={voiceReplies}
                        onCheckedChange={setVoiceReplies}
                        aria-label="Toggle spoken replies"
                      />
                    </div>
                  </CardContent>
                </Card>

                {/* STT */}
                <Card>
                  <CardHeader>
                    <CardTitle>Speech-to-Text (STT)</CardTitle>
                    <CardDescription>Transcription backend used for microphone input</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="grid gap-4 sm:grid-cols-3">
                      <FieldRow>
                        <Label>Provider</Label>
                        <Input
                          value={sttProvider}
                          onChange={(e) => setSttProvider(e.target.value)}
                          placeholder="e.g. whisper"
                        />
                      </FieldRow>
                      <FieldRow>
                        <Label>Model</Label>
                        <Input
                          value={sttModel}
                          onChange={(e) => setSttModel(e.target.value)}
                          placeholder="e.g. base, large-v3"
                        />
                      </FieldRow>
                      <FieldRow>
                        <Label>Language</Label>
                        <Input
                          value={sttLanguage}
                          onChange={(e) => setSttLanguage(e.target.value)}
                          placeholder="e.g. en, zh, auto"
                        />
                      </FieldRow>
                    </div>
                    {(sttProvider || "").toLowerCase() === "whisper" && (
                      <p className="mt-4 text-xs text-muted-foreground">
                        Local Whisper downloads its model (~150 MB for “base”) the first time you transcribe, which can
                        take a few minutes. The mic button will appear to spin during that download.
                      </p>
                    )}
                  </CardContent>
                </Card>

                {/* TTS */}
                <Card>
                  <CardHeader>
                    <CardTitle>Text-to-Speech (TTS)</CardTitle>
                    <CardDescription>Voice synthesis backend for spoken replies</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid gap-4 sm:grid-cols-2">
                      <FieldRow>
                        <Label>Provider</Label>
                        <Select value={ttsProvider} onValueChange={setTtsProvider}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select TTS provider" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="disabled">Disabled</SelectItem>
                            <SelectItem value="system">System</SelectItem>
                            <SelectItem value="openai">OpenAI</SelectItem>
                            <SelectItem value="gemini">Gemini</SelectItem>
                            <SelectItem value="dashscope">DashScope</SelectItem>
                            <SelectItem value="grok">Grok</SelectItem>
                            <SelectItem value="qwen">Qwen</SelectItem>
                          </SelectContent>
                        </Select>
                      </FieldRow>
                      <FieldRow>
                        <Label>Voice</Label>
                        <Input
                          value={ttsVoice}
                          onChange={(e) => setTtsVoice(e.target.value)}
                          placeholder="e.g. nova, alloy, echo"
                        />
                      </FieldRow>
                      <FieldRow>
                        <Label>Model</Label>
                        <Input
                          value={ttsModel}
                          onChange={(e) => setTtsModel(e.target.value)}
                          placeholder="e.g. tts-1, tts-1-hd"
                        />
                      </FieldRow>
                      <FieldRow>
                        <Label>Language</Label>
                        <Input
                          value={ttsLanguage}
                          onChange={(e) => setTtsLanguage(e.target.value)}
                          placeholder="e.g. en, zh"
                        />
                      </FieldRow>
                    </div>

                    <div className="space-y-2">
                      <Label>DashScope API key</Label>
                      <div className="flex items-center gap-3">
                        <Input
                          type="password"
                          value={dashscopeKey}
                          onChange={(e) => setDashscopeKey(e.target.value)}
                          placeholder={
                            modelConfig?.tts_api_key_saved
                              ? "•••••••••  saved — paste a new key to replace"
                              : "Required for the DashScope and Qwen voice providers"
                          }
                          className="flex-1"
                        />
                        {!dashscopeKey.trim() && modelConfig?.tts_api_key_saved && (
                          <Badge variant="success" className="shrink-0 justify-center">
                            <Check className="size-3" />
                            Saved
                          </Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Used by the DashScope and Qwen voice providers; saved with “Save voice settings”.
                      </p>
                    </div>

                    <Separator />

                    <div className="flex items-center justify-between">
                      <Button
                        variant="outline"
                        onClick={testVoice}
                        disabled={testingVoice}
                      >
                        {testingVoice ? (
                          <Loader2 className="mr-2 size-4 animate-spin" />
                        ) : (
                          <Volume2 className="mr-2 size-4" />
                        )}
                        Test voice
                      </Button>
                      <Button onClick={saveVoice} disabled={voiceSaving}>
                        {voiceSaving && <Loader2 className="mr-2 size-4 animate-spin" />}
                        Save voice settings
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              </>
            )}
          </TabsContent>

          {/* ── APPEARANCE ─────────────────────────────────────────────────── */}
          <TabsContent value="appearance" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Theme</CardTitle>
                <CardDescription>Choose your preferred color scheme</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex gap-3">
                  <Button
                    variant={theme === "dark" ? "default" : "outline"}
                    className="flex-1"
                    onClick={() => setTheme("dark")}
                  >
                    <Moon className="mr-2 size-4" />
                    Dark
                  </Button>
                  <Button
                    variant={theme === "light" ? "default" : "outline"}
                    className="flex-1"
                    onClick={() => setTheme("light")}
                  >
                    <Sun className="mr-2 size-4" />
                    Light
                  </Button>
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  Your preference is synced with the server and persisted across sessions.
                </p>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── ADVANCED ───────────────────────────────────────────────────── */}
          <TabsContent value="advanced" className="space-y-4">
            {configLoading ? (
              <SectionSkeleton />
            ) : (
              <>
                <Card>
                  <CardHeader>
                    <CardTitle>Edge Tool Routing</CardTitle>
                    <CardDescription>
                      How tools are discovered and dispatched across connected edge devices
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-6">
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <p className="text-sm font-medium">Dynamic routing</p>
                        <p className="text-xs text-muted-foreground">
                          Automatically select the best edge device for each tool call based on availability
                        </p>
                      </div>
                      <Switch
                        checked={dynamicRouting}
                        onCheckedChange={setDynamicRouting}
                        aria-label="Enable dynamic routing"
                      />
                    </div>

                    <Separator />

                    <FieldRow>
                      <Label>Retrieval limit</Label>
                      <Input
                        type="number"
                        min={0}
                        max={200}
                        value={retrievalLimit}
                        onChange={(e) => setRetrievalLimit(Number(e.target.value))}
                        className="w-28"
                      />
                      <p className="text-xs text-muted-foreground">
                        Maximum number of edge tools retrieved per request (0–200). Set to 0 to disable retrieval.
                      </p>
                    </FieldRow>

                    <div className="flex justify-end">
                      <Button onClick={saveAdvanced} disabled={advancedSaving}>
                        {advancedSaving && <Loader2 className="mr-2 size-4 animate-spin" />}
                        Save advanced settings
                      </Button>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Configuration Storage</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-muted-foreground">
                      Settings are persisted server-side in your Yumi data directory
                      (typically{" "}
                      <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">~/.yumi/config.json</code>
                      ), with sessions and usage in{" "}
                      <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">~/.yumi/yumi.db</code>. API keys
                      are kept on the server and never returned to the browser in full. Run{" "}
                      <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">yumi --config</code> to open the
                      config file.
                    </p>
                  </CardContent>
                </Card>
              </>
            )}
          </TabsContent>
        </Tabs>
      </PageBody>
    </div>
  )
}
