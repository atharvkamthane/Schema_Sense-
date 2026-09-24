# SchemaSense AI - Mentor Handoff (Mar 27, 2026)

## 1) Executive Summary
SchemaSense AI is an autonomous AI agent system that ingests tabular data, builds schema intelligence, profiles quality, and supports NL-to-SQL querying through a local LLM (qwen3.5:4b on Ollama).

This handoff summarizes:
- Current architecture (backend + frontend)
- Exact file/module responsibilities
- API contracts currently in use
- What has been implemented so far
- Changes requested by frontend team and integrated in backend
- Known issues and technical debt
- Recommended next guidance points for mentor review

## 2) Project Goals and Constraints

### Goals
- Connect uploaded dataset(s) quickly
- Auto-build data dictionary
- Infer relationships (explicit + implicit)
- Score quality metrics (including freshness/consistency)
- Allow natural language querying over database
- Provide frontend UI for upload, dictionary, chat, quality, and 3D visualization integration

### Constraints
- Local-first AI stack
- qwen3.5:4b via Ollama (configurable via OLLAMA_MODEL)
- Local-first stack suitable for modest GPU/RAM (4B-class models)
- Backend exposed through ngrok for frontend integration

## 3) Current Repository Structure

Top-level relevant folders/files:
- backend/
- frontend/
- srs_text.txt
- MEMBER_2_BUG_REPORT.md
- MEMBER_2_TEST_PROTOCOL.md
- BACKEND_CSV_FIX_COMPLETE.md
- QUICK_REFERENCE.md
- LLM_PROMPT_FIX_COMPLETE.md

Backend current files:
- main.py
- schema.py
- quality.py
- llm.py
- sql_runner.py
- ingest_handler.py
- intelligent_schema.py
- auth.py
- requirements.txt
- database.sqlite
- uploads/
- test_api_contracts.py
- test_csv_ingest.py
- test_schema.py

Frontend current files (src):
- App.jsx
- api/api.js
- screens/UploadScreen.jsx
- screens/DictionaryScreen.jsx
- screens/ChatScreen.jsx
- screens/QualityScreen.jsx

## 4) System Architecture (Current)

## 4.1 High-level flow
1. Frontend uploads file to POST /ingest/file
2. Backend writes/merges data into database.sqlite
3. Frontend calls GET /schema, GET /relationships, GET /quality
4. Chat sends POST /query (or /query/stream)
5. Backend uses llm.py + sql_runner.py to generate, validate, execute, and explain SQL

## 4.2 Backend component roles
- main.py: FastAPI app, endpoint wiring, integration orchestration
- ingest_handler.py: CSV/ZIP/SQLite ingest logic
- schema.py: schema extraction + relationship detection + intelligent column merge
- intelligent_schema.py: heuristic PK/FK + null/uniqueness profiling from DataFrames
- quality.py: table quality scoring (completeness/freshness/consistency + orphan checks)
- llm.py: prompt templates, LLM request wrappers, schema context generation, SQL cleanup
- sql_runner.py: read-only SQL guard/execution and queried-table extraction
- auth.py: Clerk JWT verification (mock fallback mode when issuer env not set)

## 4.3 Frontend component roles
- UploadScreen: uploads files, simple status + error handling
- DictionaryScreen: fetches /schema and displays tables/columns
- ChatScreen: sends /query requests and renders SQL/explanation/results
- QualityScreen: fetches /quality and renders health bars (currently has mock fallback behavior)
- App: navigation among screens (Upload, Dictionary, Chat, Quality)

## 5) API Endpoints (Current Behavior)

### Core endpoints
- GET / : backend status
- GET /me : auth sanity check
- GET /health/llm : Ollama / configured model health

### Schema and graph endpoints
- GET /schema
  - Returns schema.extract_schema()
  - Includes tables[], links[]
  - Columns now include intelligent keys (null_percentage, is_primary_key, is_foreign_key, references) plus compatibility aliases

- GET /relationships
  - Returns object with:
    - nodes: schema tables
    - edges: relationships from schema.extract_relationships().relationships
  - Ensures edge type is explicit/implicit for frontend graph behavior

- POST /graph-data
  - Returns:
    - schema
    - relationships (raw output from schema.extract_relationships)
    - quality summary

### Ingestion endpoints
- POST /ingest/clear
  - Deletes database.sqlite

- POST /ingest/file
  - Supports .csv, .zip, .sqlite, .db
  - CSV: create_table_from_csv
  - SQLite/DB: copy_sqlite_database merge
  - ZIP: process_zip_file and load csv files inside

### Quality endpoints
- GET /quality/{table_name}
  - Returns table-level quality and column metrics
- GET /quality
  - Returns summary list (table + health score + column_count)

### NL to SQL endpoints
- POST /chat
- POST /query (alias to /chat)
- POST /query/stream (SSE)
- POST /table-reasoning (non-SQL table explanation endpoint)

## 6) NL-to-SQL Engine Logic (Implemented)

1. Determine relevant tables from user query
2. Build schema context with sample values
3. Prompt qwen3.5:4b to generate SQL
4. Cleanup model output (strip tokens/markdown)
5. Validate/execute read-only via sql_runner
6. Self-heal on SQL error via prompt_fix_sql
7. Fallback to safe SELECT if unrecoverable
8. Generate one-line explanation with row count

### Reliability additions already integrated
- execution_ok, execution_error, used_fallback fields in response
- stream endpoint sends sql_chunk, execution_result, explanation_chunk, done events
- startup warmup thread for model latency reduction

## 7) Intelligent Schema Layer (Now Integrated into /schema)

Source: intelligent_schema.py and schema.py merge logic.

### Intelligent outputs per column
- null_percentage
- uniqueness
- is_primary_key
- is_foreign_key
- references

### Compatibility aliases retained in schema.py
- is_pk
- is_fk
- foreign_key
- nullable
- default
- sample

### Heuristic logic
- PK inference: unique_count == row_count and null_count == 0, weighted toward ID-like names
- FK inference: set-subset checks among ID-like columns with naming similarity checks
- Optional index creation for inferred PK/FK columns

## 8) Quality Engine (Current)

quality.py currently computes:
- completeness score
- freshness score + latest date + days_ago
- consistency score via inferred fk orphan checks
- weighted health score:
  - with freshness: 0.40 completeness + 0.30 freshness + 0.30 consistency
  - without freshness: 0.55 completeness + 0.45 consistency

It also returns per-column metrics currently shaped as:
- name
- type
- null_percent
- uniqueness_percent
- is_pk
- is_fk

And table-level fields:
- table
- health_score
- completeness
- freshness
- freshness_latest_date
- freshness_days_ago
- consistency
- orphan_issues
- columns

## 9) Frontend Status (from code + team chat history)

## 9.1 What frontend currently has in code
- Upload, Dictionary, Chat, Quality screens wired with axios calls
- API base URL defaults to ngrok URL if VITE_API_URL missing
- Quality screen still has mock fallback behavior when API fails
- Chat screen has retry behavior and network fallback

## 9.2 What Member 2 repeatedly reported/asked for
- Remove hardcoded/dummy backend behavior
- Ensure /relationships shape is { nodes, edges }
- Ensure schema/quality payloads include richer column metadata
- Keep UI usable even if backend errors (small floating warning + fallback/mocks)
- Expect badges/colors using key fields from backend payload

## 9.3 Contract assumptions from Member 2 messages
- Dictionary/quality UI expects key metadata for columns
- Visualization expects edge fields source_col/target_col and type explicit/implicit
- Quality detail rendering expects table-level freshness/consistency fields

## 10) Changes Completed During This Collaboration

1. Ingestion improvements
- Added robust csv/sqlite/zip handlers in ingest_handler.py
- Added /ingest/clear for reset flow

2. NL-to-SQL improvements
- Better prompt grounding with sample values
- SQL cleanup + fallback safety
- Streaming endpoint with SSE
- Self-correction loop for bad SQL

3. Auth integration
- Added Clerk JWT path in auth.py with mock mode fallback

4. Graph/relationships contract
- /relationships adjusted to return nodes/edges for frontend
- Relationship key normalization to source_col/target_col

5. Quality enhancements
- Added freshness/consistency + orphan issue logic
- Added richer table-level quality payload

6. Intelligent schema integration
- /schema now merges intelligent_schema outputs into column payload

## 11) Known Issues / Technical Debt (Important for Mentor)

1. Test contract drift
- test_api_contracts.py still expects old /relationships shape (mode/relationship_count/relationships with source_column/target_column).
- Runtime endpoint now returns nodes/edges for frontend compatibility.
- Action: update tests to current contract or add dual-contract adapter.

2. Inconsistent key naming between modules
- schema columns use null_percentage/uniqueness + is_primary_key/is_foreign_key plus aliases.
- quality columns use null_percent/uniqueness_percent + is_pk/is_fk.
- Action: standardize one canonical schema and keep aliases as deprecated compatibility only.

3. Potential performance concern in schema extraction
- schema.extract_schema loads full table DataFrames (SELECT * each table) for intelligent metrics.
- Large datasets may increase latency/memory.
- Action: sample/chunk mode or cached profiling pipeline.

4. Legacy docs in root can conflict
- Multiple markdown status files describe different states and may no longer all be accurate.
- Action: retain one source-of-truth handoff doc.

5. Frontend currently plain React screens
- No dedicated 3D visualization file in current frontend folder snapshot.
- Member 2 communications mention visualization integration; likely external/in-progress branch.

## 12) Runbook (Current)

## 12.1 Backend setup
1. Use Python virtualenv (already present as env/)
2. Install deps: pip install -r backend/requirements.txt
3. Run backend:
   - cd backend
   - python main.py

## 12.2 Frontend setup
1. cd frontend
2. npm install
3. npm run dev
4. Set VITE_API_URL when needed, else default ngrok URL in api.js is used

## 12.3 Basic verification checklist
1. POST /ingest/file with csv
2. GET /schema returns uploaded table and intelligent column fields
3. GET /relationships returns nodes/edges
4. GET /quality returns summary items
5. POST /query returns sql + data + explanation

## 13) Suggested Mentor Guidance Topics

1. API contract freeze
- Finalize schema for /schema, /relationships, /quality to avoid frontend/backend drift.

2. Performance strategy
- Decide whether intelligent profiling should run sync in request path or async/cache.

3. Testing strategy
- Update tests to current contracts and add integration tests for ingest -> schema -> query flow.

4. Deployment hardening
- Environment-variable management for ngrok/clerk/ollama URLs.
- CORS tightening for production.

5. Security
- Ensure query endpoint remains read-only and resistant to prompt/SQL injection patterns.

6. Demo path
- Lock one golden dataset and one golden script for 3-minute demo reliability.

## 14) Practical Notes for Next Team Sync

- Backend now supports CSV, ZIP, SQLite uploads and schema intelligence overlay.
- Frontend has endpoint wiring but still contains fallback patterns in places.
- Team should decide final source of truth for:
  - key names (is_pk vs is_primary_key, etc.)
  - relationships payload structure across /relationships and /graph-data
  - expected data shape for quality details UI

## 15) Snapshot of Member Responsibilities (SRS + Current)

- Member 1 (Backend/AI): ingestion, schema extraction, quality profiling, LLM query pipeline, API reliability
- Member 2 (Frontend/UI): upload, dictionary, chat, quality UI, endpoint integration, UX/error handling, deployment wiring
- Member 3 (3D/Demo): ER graph behavior, visualization effects, demo-critical presentation polish

## 16) Final Status Summary

Project is in an advanced integration stage:
- Core backend flows are functional and significantly improved
- Intelligent schema metadata is now available in /schema
- Relationship format aligned for graph nodes/edges
- Quality scoring includes freshness and consistency concepts
- Remaining risk is mostly contract standardization, test updates, and frontend final sync polish

---
Prepared for mentor review on Mar 27, 2026.
If needed, this file can be split into:
- TECHNICAL_ARCHITECTURE.md
- API_CONTRACT.md
- TEAM_PROGRESS.md
for easier ongoing maintenance.
