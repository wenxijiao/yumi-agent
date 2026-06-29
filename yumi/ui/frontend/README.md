# Yumi Web UI

The Yumi web UI — a **React + Vite + TypeScript + Tailwind** single-page app.
It is a pure client of the core HTTP API (see `docs/HTTP_API.md`); it never
imports Python.

## How it ships

`npm run build` compiles the app to **`yumi/ui/static/`** (configured via Vite's
`build.outDir`). Those static assets are included in the Python package
(`pyproject.toml` → `package-data: ui/static/**/*`) and served by the core
server under **`/app`** (`_mount_spa` in `yumi/core/api/app_factory.py`).

End users therefore need **no Node and no build step** — `yumi --ui` just opens
the browser at the running server. Only maintainers building the package need
Node.

## Develop

```bash
cd yumi/ui/frontend
npm install
npm run dev          # Vite dev server on http://localhost:5173
```

The dev server proxies all API paths (`/chat`, `/memory`, `/config`, `/tools`,
`/monitor`, `/stats`, `/stt`, `/tts`, `/timers`, `/timer-events`, `/uploads`,
`/health`, `/clear`) to `http://127.0.0.1:8000` (override with `YUMI_SERVER_URL`).
So run `yumi --server` in another terminal first.

## Build (after any UI change)

```bash
cd yumi/ui/frontend
npm install          # first time only
npm run build        # type-checks, then emits yumi/ui/static/
```

Commit the regenerated `yumi/ui/static/` so the package ships the latest UI.

## Layout

- `src/lib/` — API client (`api.ts`), types, formatters
- `src/components/ui/` — shadcn-style primitives (Button, Dialog, Tabs, …)
- `src/components/layout/` — nav rail, app shell, page header
- `src/components/chat/` — chat view, composer, messages, sessions sidebar
- `src/pages/` — one file per route (chat, tools, stats, settings, timers, memory, setup)
- `src/hooks/` — `use-chat`, react-query hooks, theme
- `src/store/` — small Zustand store (app)
- `src/index.css` — design tokens (dark-first) + Tailwind v4 theme
