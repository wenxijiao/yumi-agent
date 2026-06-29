import * as React from "react"
import { useNavigate } from "react-router-dom"
import { Search, MessageSquare, Bot, Clock, Sparkles } from "lucide-react"
import { toast } from "sonner"

import { PageHeader, PageBody } from "@/components/layout/page"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardFooter } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { timeAgo } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useApp } from "@/store/app"
import type { SearchResult } from "@/lib/types"

const EXAMPLE_QUERIES = [
  "What did we discuss about Python?",
  "Remind me about my project ideas",
  "What tools did we use last week?",
  "Summarise our chat about APIs",
]

function ResultCard({ result }: { result: SearchResult }) {
  const navigate = useNavigate()
  const setActiveSessionId = useApp((s) => s.setActiveSessionId)

  function openChat() {
    setActiveSessionId(result.session_id)
    navigate("/")
  }

  return (
    <Card className="overflow-hidden">
      <CardContent className="pt-4 pb-2">
        <div className="mb-2 flex items-center gap-2">
          {result.role === "user" ? (
            <Badge variant="secondary" className="gap-1 text-xs">
              <MessageSquare className="size-3" />
              User
            </Badge>
          ) : (
            <Badge variant="outline" className="gap-1 text-xs">
              <Bot className="size-3" />
              Assistant
            </Badge>
          )}
          {result.score !== undefined && (
            <span className="text-xs text-muted-foreground">
              {(result.score * 100).toFixed(0)}% match
            </span>
          )}
        </div>
        <p
          className={cn(
            "whitespace-pre-wrap text-sm leading-relaxed text-foreground",
            "line-clamp-4",
          )}
        >
          {result.content}
        </p>
      </CardContent>
      <CardFooter className="flex items-center justify-between border-t border-border px-4 py-2">
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <Clock className="size-3" />
          {result.timestamp ? timeAgo(result.timestamp) : "Unknown time"}
        </div>
        <Button variant="ghost" size="sm" onClick={openChat}>
          Open chat
        </Button>
      </CardFooter>
    </Card>
  )
}

function SkeletonResults() {
  return (
    <div className="flex flex-col gap-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <Card key={i} className="overflow-hidden">
          <CardContent className="pt-4 pb-2">
            <div className="mb-2 flex items-center gap-2">
              <Skeleton className="h-5 w-16 rounded-full" />
            </div>
            <Skeleton className="mb-1.5 h-4 w-full" />
            <Skeleton className="mb-1.5 h-4 w-5/6" />
            <Skeleton className="mb-1.5 h-4 w-4/6" />
            <Skeleton className="h-4 w-3/6" />
          </CardContent>
          <CardFooter className="flex items-center justify-between border-t border-border px-4 py-2">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-8 w-24" />
          </CardFooter>
        </Card>
      ))}
    </div>
  )
}

export function MemoryPage() {
  const [query, setQuery] = React.useState("")
  const [results, setResults] = React.useState<SearchResult[]>([])
  const [loading, setLoading] = React.useState(false)
  const [hasSearched, setHasSearched] = React.useState(false)

  async function runSearch(q: string) {
    const trimmed = q.trim()
    if (!trimmed) return
    setLoading(true)
    setHasSearched(true)
    try {
      const data = await api.searchMemory(trimmed)
      setResults(data)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Search failed")
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    runSearch(query)
  }

  function handleChip(example: string) {
    setQuery(example)
    runSearch(example)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault()
      runSearch(query)
    }
  }

  return (
    <>
      <PageHeader
        icon={Search}
        title="Memory"
        description="Search everything you've discussed with Yumi."
      />
      <PageBody>
        {/* Search bar */}
        <form onSubmit={handleSubmit} className="mb-6 flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search your conversation history…"
              className="pl-9"
              autoFocus
            />
          </div>
          <Button type="submit" disabled={!query.trim() || loading}>
            Search
          </Button>
        </form>

        {/* States */}
        {loading ? (
          <SkeletonResults />
        ) : !hasSearched ? (
          /* Pre-search hint */
          <div className="flex flex-col items-center gap-6 pt-12 text-center">
            <div className="flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <Sparkles className="size-7" />
            </div>
            <div>
              <p className="mb-1 font-semibold tracking-tight">Search your memory</p>
              <p className="max-w-sm text-sm text-muted-foreground">
                Yumi remembers everything. Type a question or topic to find related conversations.
              </p>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              {EXAMPLE_QUERIES.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => handleChip(q)}
                  className="rounded-full border border-border bg-muted px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/10 hover:text-primary"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : results.length === 0 ? (
          /* No results */
          <div className="flex flex-col items-center gap-4 pt-12 text-center">
            <div className="flex size-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
              <Search className="size-7" />
            </div>
            <div>
              <p className="mb-1 font-semibold tracking-tight">No matches found</p>
              <p className="text-sm text-muted-foreground">
                Try different keywords or a broader phrase.
              </p>
            </div>
          </div>
        ) : (
          /* Results list */
          <div className="flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">
              {results.length} result{results.length !== 1 ? "s" : ""} for &ldquo;{query}&rdquo;
            </p>
            {results.map((r) => (
              <ResultCard key={r.id} result={r} />
            ))}
          </div>
        )}
      </PageBody>
    </>
  )
}
