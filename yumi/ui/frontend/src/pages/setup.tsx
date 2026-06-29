import { useEffect, useState } from "react"
import type { ElementType, ReactNode } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import {
  Sparkles,
  ChevronRight,
  ChevronLeft,
  Check,
  Server,
  Brain,
  Zap,
  Globe,
  Bot,
} from "lucide-react"
import { api } from "@/lib/api"
import type { ModelConfig } from "@/lib/types"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"

// ── Provider metadata ──────────────────────────────────────────────────────

interface ProviderMeta {
  id: string
  label: string
  description: string
  icon: ElementType
  iconColor: string
  iconBg: string
  apiKeyLabel?: string
  apiKeySaved?: (cfg: ModelConfig) => boolean
}

const PROVIDERS: ProviderMeta[] = [
  {
    id: "ollama",
    label: "Ollama",
    description: "Local & private, no API key",
    icon: Server,
    iconColor: "text-emerald-500",
    iconBg: "bg-emerald-500/12",
  },
  {
    id: "openai",
    label: "OpenAI",
    description: "GPT-4o and GPT-4 Turbo",
    icon: Brain,
    iconColor: "text-green-500",
    iconBg: "bg-green-500/12",
    apiKeyLabel: "OpenAI API Key",
    apiKeySaved: (c) => !!c.openai_api_key_saved,
  },
  {
    id: "gemini",
    label: "Gemini",
    description: "Google multimodal AI",
    icon: Zap,
    iconColor: "text-blue-500",
    iconBg: "bg-blue-500/12",
    apiKeyLabel: "Gemini API Key",
    apiKeySaved: (c) => !!c.gemini_api_key_saved,
  },
  {
    id: "claude",
    label: "Claude",
    description: "Anthropic — helpful & safe",
    icon: Sparkles,
    iconColor: "text-primary",
    iconBg: "bg-primary/12",
    apiKeyLabel: "Anthropic API Key",
    apiKeySaved: (c) => !!c.claude_api_key_saved,
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    description: "High-performance reasoning",
    icon: Globe,
    iconColor: "text-cyan-500",
    iconBg: "bg-cyan-500/12",
    apiKeyLabel: "DeepSeek API Key",
    apiKeySaved: (c) => !!c.deepseek_api_key_saved,
  },
  {
    id: "grok",
    label: "Grok",
    description: "xAI real-time intelligence",
    icon: Bot,
    iconColor: "text-orange-500",
    iconBg: "bg-orange-500/12",
    apiKeyLabel: "Grok API Key",
    apiKeySaved: (c) => !!c.grok_api_key_saved,
  },
]

const MODEL_PLACEHOLDER: Record<string, string> = {
  ollama: "llama3.1",
  openai: "gpt-4o",
  gemini: "gemini-1.5-pro",
  claude: "claude-sonnet-4-6",
  deepseek: "deepseek-chat",
  grok: "grok-2",
}

const MODEL_HINT: Record<string, string> = {
  ollama: "Run 'ollama pull llama3.1' first to make the model available locally.",
  openai: "gpt-4o is recommended. gpt-3.5-turbo is faster and lower-cost.",
  gemini: "gemini-1.5-flash is great value; gemini-1.5-pro for long context.",
  claude: "claude-sonnet-4-6 offers the best balance of speed and capability.",
  deepseek: "deepseek-chat for general tasks; deepseek-coder for code.",
  grok: "grok-2 is the latest model with real-time knowledge.",
}

const EMBEDDING_PROVIDERS = [
  { id: "fastembed", label: "FastEmbed (local, recommended)" },
  { id: "openai", label: "OpenAI" },
  { id: "gemini", label: "Gemini" },
  { id: "ollama", label: "Ollama" },
]

const STEPS = ["Provider", "Model", "Review"]

// ── SetupWizard ────────────────────────────────────────────────────────────

export function SetupWizard() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [saving, setSaving] = useState(false)

  // form state
  const [provider, setProvider] = useState("ollama")
  const [apiKey, setApiKey] = useState("")
  const [model, setModel] = useState("")
  const [embeddingProvider, setEmbeddingProvider] = useState("fastembed")

  // store the full loaded config so we can derive `apiKeySaved` per provider
  const [loadedConfig, setLoadedConfig] = useState<ModelConfig | null>(null)

  useEffect(() => {
    api
      .getModelConfig()
      .then((cfg) => {
        setLoadedConfig(cfg)
        if (cfg.chat_provider) setProvider(cfg.chat_provider)
        if (cfg.chat_model) setModel(cfg.chat_model)
        if (cfg.embedding_provider) setEmbeddingProvider(cfg.embedding_provider)
      })
      .catch(() => undefined)
  }, [])

  const currentMeta = PROVIDERS.find((p) => p.id === provider)
  const needsKey = provider !== "ollama"
  const keySaved = loadedConfig ? (currentMeta?.apiKeySaved?.(loadedConfig) ?? false) : false
  // key is "provided" if the provider doesn't need one, if there's already a saved key, or if user typed one
  const keyProvided = !needsKey || keySaved || apiKey.trim().length > 0

  const canNext = (() => {
    if (step === 0) return !!provider && keyProvided
    if (step === 1) return model.trim().length > 0
    return true
  })()

  const handleProviderSelect = (id: string) => {
    setProvider(id)
    setApiKey("") // reset typed key when switching provider
  }

  const handleFinish = async () => {
    setSaving(true)
    try {
      const patch: Record<string, unknown> = {
        chat_provider: provider,
        chat_model: model.trim(),
        embedding_provider: embeddingProvider,
      }
      if (apiKey.trim() && needsKey) {
        patch[`${provider}_api_key`] = apiKey.trim()
      }
      await api.updateModelConfig(patch)
      toast.success("Setup complete! Yumi is ready.")
      navigate("/")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save configuration")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background px-4 py-10">
      {/* Decorative background glow */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 flex items-center justify-center"
      >
        <div className="size-[700px] rounded-full bg-primary/7 blur-[140px]" />
      </div>
      <div
        aria-hidden
        className="pointer-events-none absolute bottom-0 right-0 size-[360px] translate-x-1/3 translate-y-1/3 rounded-full bg-primary/5 blur-[100px]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute left-0 top-0 size-[280px] -translate-x-1/3 -translate-y-1/3 rounded-full bg-primary/4 blur-[90px]"
      />

      <Card className="relative z-10 w-full max-w-lg shadow-2xl shadow-black/15 animate-in-up">
        {/* ── Brand header ── */}
        <div className="flex flex-col items-center gap-4 px-6 pb-2 pt-8">
          <div className="brand-glow flex size-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-[#6d4aff] text-white shadow-xl shadow-primary/30">
            <Sparkles className="size-7" />
          </div>

          <div className="text-center">
            <h1 className="text-2xl font-semibold tracking-tight">Welcome to Yumi</h1>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Set up your AI agent in a few quick steps.
            </p>
          </div>

          {/* Progress dots with step labels */}
          <div className="mt-0.5 flex items-center gap-0">
            {STEPS.map((label, i) => (
              <div key={label} className="flex items-center">
                <div className="flex flex-col items-center gap-1.5">
                  <button
                    onClick={() => i < step && setStep(i)}
                    className={cn(
                      "flex size-7 items-center justify-center rounded-full text-xs font-semibold transition-all duration-200",
                      i === step
                        ? "bg-primary text-primary-foreground shadow-md shadow-primary/30 ring-2 ring-primary/20"
                        : i < step
                          ? "cursor-pointer bg-primary/20 text-primary hover:bg-primary/30"
                          : "bg-muted text-muted-foreground",
                    )}
                  >
                    {i < step ? <Check className="size-3.5" /> : i + 1}
                  </button>
                  <span
                    className={cn(
                      "text-[10px] font-medium transition-colors",
                      i === step ? "text-primary" : "text-muted-foreground",
                    )}
                  >
                    {label}
                  </span>
                </div>
                {i < STEPS.length - 1 && (
                  <div
                    className={cn(
                      "mb-4 h-px w-12 transition-colors duration-300",
                      i < step ? "bg-primary/40" : "bg-border",
                    )}
                  />
                )}
              </div>
            ))}
          </div>
        </div>

        <CardContent className="px-6 pb-6 pt-2">
          {/* ── Step 0: Provider ── */}
          {step === 0 && (
            <div className="space-y-5">
              <p className="text-xs text-muted-foreground">
                Choose the AI provider that powers your agent's conversations.
              </p>

              <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                {PROVIDERS.map((p) => {
                  const Icon = p.icon
                  const selected = provider === p.id
                  return (
                    <button
                      key={p.id}
                      onClick={() => handleProviderSelect(p.id)}
                      className={cn(
                        "flex flex-col items-start gap-2 rounded-xl border p-3 text-left transition-all duration-150",
                        selected
                          ? "border-primary/50 bg-primary/8 ring-1 ring-primary/25 shadow-sm"
                          : "border-border bg-card hover:border-primary/20 hover:bg-accent",
                      )}
                    >
                      <div
                        className={cn(
                          "flex size-8 items-center justify-center rounded-lg",
                          p.iconBg,
                        )}
                      >
                        <Icon className={cn("size-4", p.iconColor)} />
                      </div>
                      <div>
                        <div className="text-sm font-medium leading-none">{p.label}</div>
                        <div className="mt-1 text-[11px] leading-tight text-muted-foreground">
                          {p.description}
                        </div>
                      </div>
                      {selected && (
                        <div className="ml-auto mt-auto flex size-4 items-center justify-center rounded-full bg-primary text-primary-foreground">
                          <Check className="size-2.5" />
                        </div>
                      )}
                    </button>
                  )
                })}
              </div>

              {needsKey && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="api-key">
                      {currentMeta?.apiKeyLabel ?? "API Key"}
                    </Label>
                    {keySaved && !apiKey && (
                      <Badge variant="success" className="gap-1 text-[11px]">
                        <Check className="size-3" />
                        Saved
                      </Badge>
                    )}
                  </div>
                  <Input
                    id="api-key"
                    type="password"
                    placeholder={
                      keySaved ? "Leave blank to keep existing key" : "Paste your API key…"
                    }
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    autoComplete="off"
                  />
                  {!keySaved && (
                    <p className="text-[11px] text-muted-foreground">
                      Your key is stored server-side and never exposed to the browser.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── Step 1: Model ── */}
          {step === 1 && (
            <div className="space-y-5">
              <p className="text-xs text-muted-foreground">
                Specify which model to use and how to embed memory.
              </p>

              <div className="space-y-1.5">
                <Label htmlFor="chat-model">Chat model</Label>
                <Input
                  id="chat-model"
                  placeholder={MODEL_PLACEHOLDER[provider] ?? "model-name"}
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  autoFocus
                />
                {MODEL_HINT[provider] && (
                  <p className="text-[11px] text-muted-foreground">{MODEL_HINT[provider]}</p>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="embedding-provider">
                  Embedding provider
                  <span className="ml-1.5 text-[10px] font-normal text-muted-foreground">
                    optional
                  </span>
                </Label>
                <Select value={embeddingProvider} onValueChange={setEmbeddingProvider}>
                  <SelectTrigger id="embedding-provider">
                    <SelectValue placeholder="Select embedding provider" />
                  </SelectTrigger>
                  <SelectContent>
                    {EMBEDDING_PROVIDERS.map((ep) => (
                      <SelectItem key={ep.id} value={ep.id}>
                        {ep.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[11px] text-muted-foreground">
                  Used for memory similarity search. FastEmbed runs locally with no API
                  key required.
                </p>
              </div>
            </div>
          )}

          {/* ── Step 2: Review ── */}
          {step === 2 && (
            <div className="space-y-4">
              <p className="text-xs text-muted-foreground">
                Review your configuration before saving. You can adjust these anytime in
                Settings.
              </p>

              <div className="overflow-hidden rounded-xl border border-border">
                <ReviewRow label="Chat provider">
                  <div className="flex items-center gap-1.5">
                    {(() => {
                      const meta = PROVIDERS.find((p) => p.id === provider)
                      if (!meta) return <span>{provider}</span>
                      const Icon = meta.icon
                      return (
                        <>
                          <Icon className={cn("size-4", meta.iconColor)} />
                          <span>{meta.label}</span>
                        </>
                      )
                    })()}
                  </div>
                </ReviewRow>
                <ReviewRow label="Chat model">
                  <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground">
                    {model || "(not set)"}
                  </code>
                </ReviewRow>
                <ReviewRow label="Embedding">
                  <span>
                    {EMBEDDING_PROVIDERS.find((e) => e.id === embeddingProvider)?.label ??
                      embeddingProvider}
                  </span>
                </ReviewRow>
                {needsKey && (
                  <ReviewRow label="API key" last>
                    {apiKey.trim() ? (
                      <Badge variant="success" className="gap-1">
                        <Check className="size-3" />
                        Will be saved
                      </Badge>
                    ) : keySaved ? (
                      <Badge variant="success" className="gap-1">
                        <Check className="size-3" />
                        Already saved
                      </Badge>
                    ) : (
                      <Badge variant="warning">Not provided</Badge>
                    )}
                  </ReviewRow>
                )}
              </div>

              <p className="text-center text-[11px] text-muted-foreground">
                Clicking "Finish setup" will write these values to the server config.
              </p>
            </div>
          )}
        </CardContent>

        {/* ── Footer ── */}
        <div className="flex items-center justify-between border-t border-border px-6 py-4">
          <div>
            {step > 0 ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setStep((s) => s - 1)}
              >
                <ChevronLeft className="size-4" />
                Back
              </Button>
            ) : (
              <button
                onClick={() => navigate("/")}
                className="text-xs text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
              >
                Skip for now
              </button>
            )}
          </div>

          <div>
            {step < STEPS.length - 1 ? (
              <Button size="sm" disabled={!canNext} onClick={() => setStep((s) => s + 1)}>
                Next
                <ChevronRight className="size-4" />
              </Button>
            ) : (
              <Button size="sm" disabled={saving || !canNext} onClick={handleFinish}>
                {saving ? (
                  "Saving…"
                ) : (
                  <>
                    Finish setup
                    <Check className="size-4" />
                  </>
                )}
              </Button>
            )}
          </div>
        </div>
      </Card>
    </div>
  )
}

// ── Small co-located helpers ───────────────────────────────────────────────

function ReviewRow({
  label,
  children,
  last,
}: {
  label: string
  children: ReactNode
  last?: boolean
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between px-4 py-3",
        !last && "border-b border-border",
      )}
    >
      <span className="text-sm text-muted-foreground">{label}</span>
      <div className="flex items-center gap-1.5 text-sm font-medium text-foreground">
        {children}
      </div>
    </div>
  )
}
