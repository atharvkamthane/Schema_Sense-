# SchemaSense AI

**Local-first Data Dictionary Agent** — ingest CSV / SQLite / ZIP datasets, auto-build a data dictionary, infer relationships, score data quality, explore schema in 2D/3D, and ask natural-language questions that become SQL via a local Ollama LLM (`qwen3.5:4b` by default).

Stack: **React + Vite frontend**, **FastAPI backend**, **SQLite** working database, **Ollama** for local inference, optional **Clerk** auth.

---

## Table of contents

1. [Features](#features)
2. [Architecture & connections](#architecture--connections)
3. [Repository structure](#repository-structure)
4. [Prerequisites](#prerequisites)
5. [Quick start](#quick-start)
6. [Environment variables](#environment-variables)
7. [Running the stack](#running-the-stack)
8. [Frontend routes & screens](#frontend-routes--screens)
9. [Backend API reference](#backend-api-reference)
10. [Data flow](#data-flow)
11. [LLM configuration](#llm-configuration)
12. [Auth (Clerk)](#auth-clerk)
13. [Deployment notes](#deployment-notes)
14. [Tests & smoke checks](#tests--smoke-checks)
15. [Troubleshooting](#troubleshooting)

---

## Features

| Area | What it does |
|------|----------------|
| **Ingest** | Upload `.csv`, `.sqlite` / `.db`, or ZIP archives → loaded into `database.sqlite` |
| **Schema / dictionary** | Tables, columns, PK/FK heuristics, business + developer summaries |
| **Relationships** | Explicit FKs + inferred links; Mermaid + graph payloads for UI |
| **Quality** | Completeness, freshness, consistency, orphan checks, health scores |
| **Analysis** | Per-table statistical / AI-assisted analysis |
| **NL → SQL chat** | Local LLM generates SQL, runner executes read-only queries, explains results |
| **Visualization** | 2D ER diagram + 3D force-graph (`react-force-graph-3d` / Three.js) |
| **Reports** | PDF export (jsPDF) with model metadata |
| **Auth** | Optional Clerk JWT; local DEV mode if no publishable key is set |

---

## Architecture & connections

```
┌─────────────────────┐         HTTP/JSON          ┌──────────────────────────┐
│  React Frontend     │  VITE_API_URL (default     │  FastAPI Backend         │
│  Vite :5173         │  http://127.0.0.1:8000)    │  Uvicorn :8000           │
│                     │ ◄────────────────────────► │                          │
│  src/api/axios.js   │  Authorization: Bearer …   │  main.py                 │
│  src/api/api.js     │  ngrok-skip-browser-warning│  ingest → schema → LLM   │
└─────────┬───────────┘                            └────────────┬─────────────┘
          │                                                     │
          │ Optional Clerk                                      ├── SQLite
          ▼                                                     │   database.sqlite
┌─────────────────────┐                                         │   (cwd: Backend/backend)
│  Clerk (cloud)       │                                         │
│  sign-in / JWT      │                                         ├── uploads/
└─────────────────────┘                                         │
                                                                ▼
                                                   ┌──────────────────────────┐
                                                   │  Ollama :11434           │
                                                   │  POST /api/generate      │
                                                   │  model: qwen3.5:4b       │
                                                   │  (OLLAMA_MODEL)          │
                                                   └──────────────────────────┘
```

### How pieces talk

| From | To | Mechanism |
|------|-----|-----------|
| Browser UI | FastAPI | Axios (`src/api/axios.js`) base URL = `VITE_API_URL` |
| Streaming chat | FastAPI | `fetch` + SSE on `/query/stream` (`streamColumnChat` in `api.js`) |
| FastAPI | SQLite | `database.sqlite` in `Backend/backend/` via `schema.py`, `ingest_handler.py`, `sql_runner.py` |
| FastAPI | Ollama | `requests` → `http://127.0.0.1:11434/api/generate` (`llm.py`) |
| Frontend | Clerk | `@clerk/clerk-react` when `VITE_CLERK_PUBLISHABLE_KEY` is set |
| FastAPI | Clerk | JWT verify via `CLERK_ISSUER_URL` (`auth.py`); **mock user** if unset |

### Request path (happy path)

1. User uploads file → `POST /ingest/file` → rows land in `database.sqlite`
2. UI loads dictionary → `GET /schema`, `GET /relationships`, `GET /quality`
3. User asks a question → `POST /query` or `/query/stream`
4. Backend builds schema context → Ollama generates SQL → `sql_runner` executes → LLM explains

---

## Repository structure

```
Schema_Sense-/
├── README.md                 ← this file
├── package.json              ← frontend (schemasense-frontend)
├── vite.config.js
├── tailwind.config.cjs
├── postcss.config.cjs
├── eslint.config.js
├── vercel.json               ← SPA rewrites for Vercel
├── index.html
├── .env                      ← local frontend env (not committed)
├── .env.example
├── smoke-test.js / .cjs
│
├── public/                   ← static assets
│
├── src/                      ← ★ PRIMARY FRONTEND
│   ├── main.jsx              ← entry; ClerkProvider only if key present
│   ├── App.jsx               ← routes, sidebar layout, auth gate
│   ├── index.css / App.css
│   ├── api/
│   │   ├── axios.js          ← Axios instance, baseURL, global errors
│   │   └── api.js            ← typed helpers + streaming + retries
│   ├── screens/
│   │   ├── LandingPage.jsx
│   │   ├── SignInScreen.jsx / SignUpScreen.jsx
│   │   ├── DashboardScreen.jsx
│   │   ├── UploadScreen.jsx
│   │   ├── DictionaryScreen.jsx
│   │   ├── Visualization3D.jsx
│   │   ├── QualityScreen.jsx
│   │   ├── AnalysisScreen.jsx
│   │   └── ChatScreen.jsx
│   ├── components/
│   │   ├── landing/          ← marketing sections
│   │   ├── DBViz3D.jsx       ← 3D schema graph
│   │   ├── ERDiagram2D.jsx
│   │   ├── AIAssistantModal.jsx
│   │   ├── AnalyticsDashboard.jsx
│   │   ├── GlobalQualityReport.jsx
│   │   ├── NodeDetailOverlay.jsx
│   │   ├── PDFExportModal.jsx
│   │   └── effects/
│   ├── store/
│   │   ├── useAppStore.js           ← Zustand: schema, errors, app state
│   │   └── useVisualizationStore.js
│   ├── utils/
│   │   └── reportData.js
│   └── assets/
│
└── Backend/
    ├── backend/              ← ★ PRIMARY BACKEND (run uvicorn from here)
    │   ├── main.py           ← FastAPI app + all HTTP routes
    │   ├── ingest_handler.py ← CSV / SQLite / ZIP → database.sqlite
    │   ├── schema.py         ← extract schema + relationships
    │   ├── intelligent_schema.py  ← PK/FK / profiling heuristics
    │   ├── quality.py        ← quality scoring
    │   ├── llm.py            ← Ollama client, prompts, health_check
    │   ├── new_llm_funcs.py  ← table analysis prompts
    │   ├── sql_runner.py     ← read-only SQL guard + execute
    │   ├── analysis.py       ← table analysis helpers
    │   ├── auth.py           ← Clerk JWT or local mock user
    │   ├── requirements.txt
    │   ├── .env              ← OLLAMA_MODEL, etc.
    │   ├── database.sqlite   ← working DB (created/updated by ingest)
    │   ├── uploads/          ← saved upload files
    │   ├── .venv/            ← Python virtualenv (local)
    │   └── test_*.py         ← API / ingest / schema tests
    │
    ├── 3D_diagram/           ← standalone/experimental 3D viz app (Vite+TS)
    ├── self-hosted-ai-starter-kit/  ← optional n8n / Docker AI kit (reference)
    ├── PROJECT_MENTOR_HANDOFF_2026-03-27.md
    ├── QUICK_REFERENCE.md
    └── …                     ← historical bug/fix notes, duplicate Vite scaffold
```

> **Note:** `Backend/` also contains an older/duplicate Vite frontend scaffold (`Backend/package.json`, etc.). The app you should run day-to-day is the **repo root** frontend + **`Backend/backend`** API.

### Backend module map

| File | Role |
|------|------|
| `main.py` | CORS, routes, orchestration, SSE streaming |
| `ingest_handler.py` | Parse uploads into SQLite tables |
| `schema.py` | Tables/columns/relationships (+ intelligent overlay) |
| `intelligent_schema.py` | Heuristic PK/FK, null/uniqueness profiling |
| `quality.py` | Per-table / global quality metrics |
| `llm.py` | Prompts, `ask_llm` / `ask_llm_stream`, SQL/JSON cleaners |
| `sql_runner.py` | Validate & run SELECT-style queries safely |
| `analysis.py` | Numeric/categorical/date stats for analysis endpoints |
| `auth.py` | Optional Clerk issuer validation |

---

## Prerequisites

| Tool | Version / notes |
|------|------------------|
| **Node.js** | 18+ recommended (project tested with Node 22) |
| **npm** | Comes with Node |
| **Python** | 3.10+ |
| **Ollama** | [https://ollama.com](https://ollama.com) — must be running on port `11434` |
| **Model** | Default: `qwen3.5:4b` (`ollama pull qwen3.5:4b`) |
| **RAM/VRAM** | 4B-class models need modest hardware; larger models need more RAM and may need a higher timeout |

Optional:

- **Clerk** account for production-style auth
- **ngrok** (or similar) if exposing the local API to a hosted frontend (e.g. Vercel)

---

## Quick start

### 1. Clone & frontend deps

```bash
cd Schema_Sense-
npm install
```

### 2. Backend deps

```bash
cd Backend/backend
python -m venv .venv

# Windows
.\.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
```

> `sentence-transformers` / `torch` make the first install large and slow — that is expected.

### 3. Ollama model

```bash
ollama pull qwen3.5:4b
ollama list   # confirm qwen3.5:4b is present
```

### 4. Env files

**Repo root** `.env`:

```env
VITE_API_URL=http://127.0.0.1:8000
# VITE_CLERK_PUBLISHABLE_KEY=pk_test_...   # optional
```

**`Backend/backend/.env`:**

```env
OLLAMA_MODEL=qwen3.5:4b
# OLLAMA_URL=http://127.0.0.1:11434/api/generate
# OLLAMA_TIMEOUT_SECONDS=90
# OLLAMA_KEEP_ALIVE=10m
# OLLAMA_THINK=false
# LLM_MAX_RELEVANT_TABLES=6
# CLERK_ISSUER_URL=https://your-instance.clerk.accounts.dev
```

### 5. Start services (two terminals)

```bash
# Terminal A — API (must run with cwd = Backend/backend so database.sqlite resolves)
cd Backend/backend
.\.venv\Scripts\python.exe main.py
# → http://127.0.0.1:8000

# Terminal B — UI
cd Schema_Sense-
npm run dev
# → http://localhost:5173
```

### 6. Smoke check

- Browser: http://localhost:5173  
- API: http://127.0.0.1:8000/health → `{"status":"ok"}`  
- LLM: http://127.0.0.1:8000/health/llm → `model_available: true` for `qwen3.5:4b`

Without Clerk keys, the UI runs in **DEV mode** (auth bypassed) so you can open `/upload`, `/dictionary`, etc. directly.

--- 

## Environment variables

### Frontend (Vite — repo root)

| Variable | Required | Description |
|----------|----------|-------------|
| `VITE_API_URL` | Recommended | FastAPI base URL. Default fallback in code: `http://127.0.0.1:8000` |
| `VITE_CLERK_PUBLISHABLE_KEY` | Optional | Enables ClerkProvider + protected routes |

### Backend (`Backend/backend/.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `OLLAMA_MODEL` | Optional | Default `qwen3.5:4b` |
| `OLLAMA_URL` | Optional | Default `http://127.0.0.1:11434/api/generate` |
| `OLLAMA_TIMEOUT_SECONDS` | Optional | Default `90` |
| `OLLAMA_KEEP_ALIVE` | Optional | Default `10m`; keeps the model loaded between questions for faster replies |
| `OLLAMA_THINK` | Optional | Default `false`; disables Qwen reasoning tokens for fast, deterministic SQL generation |
| `LLM_MAX_RELEVANT_TABLES` | Optional | Default `6`; limits schema context to the best matching tables |
| `CLERK_ISSUER_URL` | Optional | If unset, `/me` and auth deps use a **mock local user** |

---

## Running the stack

| Service | Command | URL |
|---------|---------|-----|
| Frontend | `npm run dev` (repo root) | http://localhost:5173 |
| Backend | `python main.py` inside `Backend/backend` (+ venv) | http://0.0.0.0:8000 |
| Ollama | system service / `ollama serve` | http://127.0.0.1:11434 |

Build frontend for production:

```bash
npm run build
npm run preview
```

---

## Frontend routes & screens

| Path | Screen | Notes |
|------|--------|--------|
| `/` | Landing | Marketing / product overview |
| `/sign-in/*` | Sign in | Clerk (when configured) |
| `/sign-up/*` | Sign up | Clerk (when configured) |
| `/dashboard` | Dashboard | Overview + AI ready status |
| `/upload` | Upload | `POST /ingest/file` |
| `/dictionary` | Data dictionary | `GET /schema` |
| `/visualization` | 2D/3D graph | `/relationships`, `/graph-data` |
| `/quality` | Quality | `GET /quality` |
| `/analysis` | Analysis | `GET /analysis/{table}` |

Protected routes wrap `MainLayout` (sidebar). If `VITE_CLERK_PUBLISHABLE_KEY` is missing, protection is skipped for local development.

### Frontend → API mapping (`src/api/api.js`)

| Helper | Backend |
|--------|---------|
| `uploadFile` | `POST /ingest/file` |
| `clearDatabase` | `POST /ingest/clear` |
| `getSchema` / `getSchemaWithCache` | `GET /schema` |
| `getRelationships` | `GET /relationships` |
| `getQuality` / `getTableQuality` | `GET /quality`, `/quality/{table}` |
| `getTableAnalysis` | `GET /analysis/{table}` |
| `getSummaryNarrative` | `POST /api/generate-summary` |
| `getGraphData` | `POST /graph-data` |
| `postQuery` / `postQueryPayload` | `POST /query` |
| `postColumnChat` | `POST /column-chat` |
| `streamColumnChat` | `POST /query/stream` (SSE) |

---

## Backend API reference

Base URL: `http://127.0.0.1:8000`  
Interactive docs (FastAPI): http://127.0.0.1:8000/docs  

### Health & auth

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Status banner |
| `GET` | `/health` | Lightweight liveness |
| `GET` | `/health/llm` | Ollama reachability + configured model |
| `GET` | `/me` | Auth probe (Clerk JWT or mock user) |

### Schema & graph

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/schema` | Tables, columns, links, Mermaid snippet |
| `GET` | `/relationships` | Nodes/edges for 3D / ER views |
| `POST` | `/graph-data` | Graph payload for visualization |

### Quality & analysis

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/quality` | Global quality |
| `GET` | `/quality/{table_name}` | Per-table quality |
| `GET` | `/analysis/{table_name}` | Table analysis (+ LLM narrative) |
| `POST` | `/api/generate-summary` | Executive / JSON summary from schema |

### Ingest

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/ingest/file` | Multipart upload (CSV / SQLite / ZIP) |
| `POST` | `/ingest/clear` | Clear working database |

### Query / LLM

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/query` | NL → SQL → execute → explain |
| `POST` | `/chat` | Chat-oriented query path |
| `POST` | `/query/stream` | SSE streaming (SQL or column chat modes) |
| `POST` | `/column-chat` | Column-scoped Q&A |
| `POST` | `/table-reasoning` | Table-level reasoning |

CORS is open (`allow_origins=["*"]`) for local / development use. Responses also set `ngrok-skip-browser-warning` for tunnel compatibility.

---

## Data flow

```
Upload (CSV/SQLite/ZIP)
        │
        ▼
  ingest_handler.py  ──►  database.sqlite
        │
        ├─► schema.py (+ intelligent_schema.py)  ──► Dictionary / Graph UI
        ├─► quality.py                           ──► Quality UI
        └─► analysis.py + llm.py                 ──► Analysis / summaries

Natural language question
        │
        ▼
  llm.build_schema_context()
        │
        ▼
  Ollama (qwen3.5:4b) ──► SQL text
        │
        ▼
  sql_runner.py (read-only) ──► rows
        │
        ▼
  llm explain / interpret ──► Chat / Assistant UI
```

Working files live under `Backend/backend/`:

- `database.sqlite` — source of truth after ingest  
- `uploads/` — original uploaded files  

---

## LLM configuration

Configured in `Backend/backend/llm.py`:

- Default model: **`qwen3.5:4b`**
- Override with env: `OLLAMA_MODEL=...`
- Generate endpoint: `OLLAMA_URL` (default local Ollama `/api/generate`)
- Task-specific sampling via `TASK_CONFIG` (`sql`, `summary`, `explain`, …)
- Output cleaners strip markdown fences and Qwen `<think>…</think>` blocks before SQL/JSON parse

Change model without code edits:

```bash
# Backend/backend/.env
OLLAMA_MODEL=qwen3.5:4b
```

Then restart the API and confirm:

```bash
curl http://127.0.0.1:8000/health/llm
```

Expected shape includes `model`, `model_available`, `installed_models` (plus legacy `phi3_available` alias for older clients).

---

## Auth (Clerk)

**Frontend**

- With `VITE_CLERK_PUBLISHABLE_KEY`: full `ClerkProvider`, `SignedIn` / `SignedOut` gates, `UserButton`
- Without key: DEV mode — routes render without sign-in; sidebar shows a `DEV` badge

**Backend**

- With `CLERK_ISSUER_URL`: validates Bearer JWT via JWKS
- Without: `get_current_user` returns `{"sub": "local_test_user", "mocked": true}`

Axios attaches Clerk tokens when a token getter is registered (`setTokenGetter` from `App.jsx`).

---

## Deployment notes

### Frontend (Vercel)

- `vercel.json` rewrites all routes to `index.html` (SPA)
- Set `VITE_API_URL` to your public API URL (ngrok / cloud host)
- Rebuild after env changes (`VITE_*` is compile-time)

### Backend

- Run from `Backend/backend` so relative paths (`database.sqlite`, `uploads/`) resolve
- Expose with ngrok / reverse proxy if the UI is hosted remotely
- Keep CORS / secrets tighter for real production (current defaults are development-friendly)

### Optional folders

- `Backend/3D_diagram` — alternate TypeScript 3D app; not required for the main product
- `Backend/self-hosted-ai-starter-kit` — Docker/n8n reference kit; not required for core SchemaSense

---

## Tests & smoke checks

From `Backend/backend` (with venv active):

```bash
python test_csv_ingest.py
python test_schema.py
python test_api_contracts.py
```

Repo root also has `smoke-test.js` / `smoke-test.cjs` for lightweight checks.

Manual checklist:

1. `GET /health` → ok  
2. `GET /health/llm` → `model_available: true`  
3. Upload a small CSV on `/upload`  
4. Dictionary shows your table (not empty / leftover demo names)  
5. Ask a simple count question in chat / assistant  
6. Quality page returns scores for your table  

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Frontend blank / Clerk error | Invalid or placeholder publishable key | Remove key for DEV mode, or set a real `VITE_CLERK_PUBLISHABLE_KEY` |
| Network / CORS errors in UI | API down or wrong `VITE_API_URL` | Confirm API on `:8000`; restart Vite after `.env` changes |
| `/schema` 500 `Database file not found` | No `database.sqlite` yet | Upload a file, or create an empty SQLite in `Backend/backend` |
| `/health/llm` `model_available: false` | Wrong tag or Ollama not running | `ollama list`, `ollama pull qwen3.5:4b`, match `OLLAMA_MODEL` |
| Chat timeouts | Slow model / cold start | Raise `OLLAMA_TIMEOUT_SECONDS`; first call may be slow |
| SQL garbage / thinking text in answers | Model reasoning tags | Already stripped in `llm.extract_sql_clean`; update prompts if needed |
| Ingest “works” but dictionary empty | API cwd wrong | Always start `main.py` from `Backend/backend` |
| Huge pip install | torch / sentence-transformers | Normal; use the project venv and wait for first install |

---

## Tech stack summary

| Layer | Tech |
|-------|------|
| UI | React 19, Vite 8, React Router 7, Tailwind 3, Framer Motion, Zustand |
| Viz | Mermaid, Recharts, Three.js, react-force-graph-3d |
| Auth UI | Clerk React (+ themes) |
| API | FastAPI, Uvicorn, Pydantic |
| Data | SQLite, Pandas, SQLAlchemy (deps), PyMySQL / psycopg2 available |
| ML / NLP deps | sentence-transformers, umap-learn (for advanced profiling paths) |
| LLM | Ollama + `qwen3.5:4b` (configurable) |
| Reports | jsPDF / reportlab |

---

## License / notes

See `Backend/self-hosted-ai-starter-kit/LICENSE` for that submodule’s license. Treat uploaded datasets as sensitive — by design, SchemaSense keeps inference **local** via Ollama so row data does not need to leave your machine for NL→SQL.
