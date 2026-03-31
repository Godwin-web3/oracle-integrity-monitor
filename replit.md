# Workspace

## Overview

pnpm workspace monorepo using TypeScript, with a Python Flask stablecoin depeg monitoring app.

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM (Node.js); SQLite (Python depeg monitor)
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)

## Structure

```text
artifacts-monorepo/
├── artifacts/
│   ├── api-server/         # Express API server (Node.js)
│   └── depeg-monitor/      # Flask stablecoin depeg monitor (Python)
├── lib/                    # Shared libraries (Node.js)
│   ├── api-spec/           # OpenAPI spec + Orval codegen config
│   ├── api-client-react/   # Generated React Query hooks
│   ├── api-zod/            # Generated Zod schemas from OpenAPI
│   └── db/                 # Drizzle ORM schema + DB connection
├── scripts/                # Utility scripts (single workspace package)
├── pnpm-workspace.yaml
├── tsconfig.base.json
├── tsconfig.json
└── package.json
```

## Stablecoin Depeg Monitor (`artifacts/depeg-monitor/`)

Python Flask web dashboard + Telegram bot for monitoring stablecoin depeg events.

- **Entry**: `app.py` — starts Flask server + Telegram bot polling + APScheduler
- **Monitor**: `monitor.py` — fetches prices from CoinGecko every 5 min, detects depeg events
- **Bot**: `bot.py` — Telegram bot with commands: /start, /help, /subscribe, /unsubscribe, /status, /setalert
- **Database**: `database.py` — SQLite (depeg_monitor.db) with subscribers, price_history, depeg_events tables
- **Template**: `templates/dashboard.html` — live dashboard UI with price cards, depeg history, price charts
- **Port**: `5000` (reads from PORT env var)
- **Secrets required**: `TELEGRAM_BOT_TOKEN`

### Tracked Stablecoins
USDT, USDC, DAI, FRAX, TUSD, PYUSD, cNGN (Nigerian Naira stablecoin), bNGN

### CoinGecko API
Public API, no key required. Rate limited. Checks every 5 minutes.

### Depeg Threshold
Default: 1% deviation from $1.00 peg. Users can customize via `/setalert` bot command.

## TypeScript & Composite Projects

Every package extends `tsconfig.base.json` which sets `composite: true`. The root `tsconfig.json` lists all packages as project references. This means:

- **Always typecheck from the root** — run `pnpm run typecheck` (which runs `tsc --build --emitDeclarationOnly`). This builds the full dependency graph so that cross-package imports resolve correctly. Running `tsc` inside a single package will fail if its dependencies haven't been built yet.
- **`emitDeclarationOnly`** — we only emit `.d.ts` files during typecheck; actual JS bundling is handled by esbuild/tsx/vite...etc, not `tsc`.
- **Project references** — when package A depends on package B, A's `tsconfig.json` must list B in its `references` array. `tsc --build` uses this to determine build order and skip up-to-date packages.

## Root Scripts

- `pnpm run build` — runs `typecheck` first, then recursively runs `build` in all packages that define it
- `pnpm run typecheck` — runs `tsc --build --emitDeclarationOnly` using project references
