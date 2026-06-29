import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowUp, Brain, FileText, ImageIcon, Loader2, Mic, Paperclip, Square, Volume2, X } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { SimpleTooltip } from "@/components/ui/tooltip"
import { useApp } from "@/store/app"
import { useModelConfig } from "@/hooks/queries"
import type { PendingFile } from "@/hooks/use-chat"
import { formatBytes } from "@/lib/format"

const DISABLED_PROVIDERS = ["", "disabled", "none", "off"]

function extForMime(mime: string): string {
  if (mime.includes("mp4") || mime.includes("m4a") || mime.includes("aac")) return "m4a"
  if (mime.includes("ogg") || mime.includes("opus")) return "ogg"
  if (mime.includes("wav")) return "wav"
  return "webm"
}

const MAX_BYTES = 25 * 1024 * 1024
const AUDIO_EXT = new Set(["ogg", "oga", "mp3", "wav", "m4a", "aac", "flac", "webm"])

function fileToBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const res = reader.result as string
      resolve(res.slice(res.indexOf(",") + 1))
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

export function Composer({
  sessionId,
  streaming,
  think,
  onToggleThink,
  onSend,
  onStop,
}: {
  sessionId: string
  streaming: boolean
  think: boolean
  onToggleThink: () => void
  onSend: (text: string, files: PendingFile[]) => void
  onStop: () => void
}) {
  const [draft, setDraft] = useState("")
  const [files, setFiles] = useState<PendingFile[]>([])
  const [uploading, setUploading] = useState(false)
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const composingRef = useRef(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const voiceReplies = useApp((s) => s.voiceReplies)
  const setVoiceReplies = useApp((s) => s.setVoiceReplies)
  const { data: modelConfig } = useModelConfig()
  const sttDisabled = modelConfig
    ? DISABLED_PROVIDERS.includes((modelConfig.stt_provider || "disabled").toLowerCase())
    : false

  const autoGrow = useCallback(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = "auto"
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`
  }, [])

  useEffect(autoGrow, [draft, autoGrow])

  const handleUpload = useCallback(
    async (list: FileList | File[]) => {
      const arr = Array.from(list)
      if (!arr.length) return
      setUploading(true)
      try {
        for (const f of arr) {
          if (f.size > MAX_BYTES) {
            toast.error(`${f.name} is too large (max 25 MB)`)
            continue
          }
          const b64 = await fileToBase64(f)
          const ext = (f.name.split(".").pop() || "").toLowerCase()
          if (AUDIO_EXT.has(ext)) {
            setTranscribing(true)
            try {
              const r = await api.transcribe(sessionId, f.name, b64)
              if (r.text) setDraft((d) => (d ? `${d}\n\n${r.text}` : r.text))
            } catch (e) {
              toast.error(`Transcription failed: ${(e as Error).message}`)
            } finally {
              setTranscribing(false)
            }
            continue
          }
          const r = await api.upload(sessionId, f.name, b64)
          if (r.path) {
            setFiles((prev) => [
              ...prev,
              { path: r.path, name: f.name, isImage: !!r.is_image, sizeLabel: formatBytes(f.size) },
            ])
          }
        }
      } catch (e) {
        toast.error(`Upload failed: ${(e as Error).message}`)
      } finally {
        setUploading(false)
      }
    },
    [sessionId],
  )

  const startRecording = useCallback(async () => {
    // getUserMedia requires a secure context — fine on localhost, but NOT over the
    // plain-http LAN URL the CLI also advertises.
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      toast.error("Voice input needs https or localhost. Open Yumi at http://127.0.0.1:8000, not a LAN IP.")
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const rec = new MediaRecorder(stream)
      chunksRef.current = []
      rec.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data)
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop())
        const mime = rec.mimeType || "audio/webm"
        const blob = new Blob(chunksRef.current, { type: mime })
        setTranscribing(true)
        try {
          const b64 = await fileToBase64(blob)
          // Filename extension must match the real container (Safari/iOS emits mp4),
          // since cloud STT providers key off it.
          const r = await api.transcribe(sessionId, `voice.${extForMime(mime)}`, b64)
          if (r.text) {
            setDraft((d) => (d ? `${d} ${r.text}` : r.text))
            taRef.current?.focus()
          } else {
            toast.message("No speech detected")
          }
        } catch (e) {
          toast.error(`Transcription failed: ${(e as Error).message}`)
        } finally {
          setTranscribing(false)
        }
      }
      rec.start()
      recorderRef.current = rec
      setRecording(true)
    } catch {
      toast.error("Microphone unavailable. Check browser permissions.")
    }
  }, [sessionId])

  const stopRecording = useCallback(() => {
    recorderRef.current?.stop()
    recorderRef.current = null
    setRecording(false)
  }, [])

  const submit = useCallback(() => {
    if (streaming) return
    if (!draft.trim() && !files.length) return
    onSend(draft, files)
    setDraft("")
    setFiles([])
    requestAnimationFrame(autoGrow)
  }, [draft, files, streaming, onSend, autoGrow])

  return (
    <div className="px-4 pb-4">
      <div className="mx-auto w-full max-w-3xl">
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            if (e.dataTransfer.files.length) handleUpload(e.dataTransfer.files)
          }}
          className={cn(
            "rounded-2xl border border-border bg-card shadow-sm transition-colors",
            dragOver && "border-primary ring-2 ring-primary/30",
          )}
        >
          {files.length > 0 && (
            <div className="flex flex-wrap gap-2 px-3 pt-3">
              {files.map((f) => (
                <div
                  key={f.path}
                  className="group flex items-center gap-2 rounded-lg border border-border bg-muted/50 py-1.5 pl-2 pr-1 text-xs"
                >
                  {f.isImage ? (
                    <ImageIcon className="size-3.5 text-primary" />
                  ) : (
                    <FileText className="size-3.5 text-muted-foreground" />
                  )}
                  <span className="max-w-[160px] truncate">{f.name}</span>
                  {f.sizeLabel && <span className="text-muted-foreground">{f.sizeLabel}</span>}
                  <button
                    onClick={() => setFiles((prev) => prev.filter((x) => x.path !== f.path))}
                    className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <textarea
            ref={taRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onCompositionStart={() => (composingRef.current = true)}
            onCompositionEnd={() => (composingRef.current = false)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !composingRef.current && !e.nativeEvent.isComposing) {
                e.preventDefault()
                submit()
              }
            }}
            rows={1}
            placeholder={recording ? "Listening…" : "Message Yumi…  (Enter to send, Shift+Enter for newline)"}
            className="max-h-[200px] w-full resize-none bg-transparent px-4 py-3.5 text-[15px] leading-relaxed outline-none placeholder:text-muted-foreground/70"
          />

          <div className="flex items-center gap-1 px-2 pb-2">
            <input
              id="file-input"
              type="file"
              multiple
              className="hidden"
              onChange={(e) => {
                if (e.target.files) handleUpload(e.target.files)
                e.target.value = ""
              }}
            />
            <SimpleTooltip label="Attach files (images, PDFs, audio)">
              <Button
                variant="ghost"
                size="icon-sm"
                disabled={uploading}
                onClick={() => document.getElementById("file-input")?.click()}
              >
                {uploading ? <Loader2 className="size-4 animate-spin" /> : <Paperclip className="size-4" />}
              </Button>
            </SimpleTooltip>

            <SimpleTooltip
              label={
                sttDisabled
                  ? "Enable speech-to-text in Settings → Voice"
                  : recording
                    ? "Stop & transcribe"
                    : "Voice input"
              }
            >
              <Button
                variant={recording ? "destructive" : "ghost"}
                size="icon-sm"
                disabled={transcribing || (sttDisabled && !recording)}
                onClick={recording ? stopRecording : startRecording}
              >
                {transcribing ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : recording ? (
                  <Square className="size-4" />
                ) : (
                  <Mic className="size-4" />
                )}
              </Button>
            </SimpleTooltip>

            <SimpleTooltip label={think ? "Deep thinking: on" : "Deep thinking: off"}>
              <Button
                variant={think ? "default" : "ghost"}
                size="sm"
                className={cn("gap-1.5", !think && "text-muted-foreground")}
                onClick={onToggleThink}
              >
                <Brain className="size-4" />
                Think
              </Button>
            </SimpleTooltip>

            <SimpleTooltip label={voiceReplies ? "Spoken replies: on" : "Spoken replies: off"}>
              <Button
                variant={voiceReplies ? "default" : "ghost"}
                size="icon-sm"
                className={cn(!voiceReplies && "text-muted-foreground")}
                onClick={() => setVoiceReplies(!voiceReplies)}
              >
                <Volume2 className="size-4" />
              </Button>
            </SimpleTooltip>

            <div className="ml-auto">
              {streaming ? (
                <Button size="icon" variant="secondary" onClick={onStop}>
                  <Square className="size-4" />
                </Button>
              ) : (
                <Button size="icon" onClick={submit} disabled={!draft.trim() && !files.length}>
                  <ArrowUp className="size-4" />
                </Button>
              )}
            </div>
          </div>
        </div>
        <p className="mt-2 text-center text-xs text-muted-foreground/70">
          Yumi can use tools and make mistakes. Verify important results.
        </p>
      </div>
    </div>
  )
}
