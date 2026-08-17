# Semantic NL-to-SQL Research Architecture — Implementation Plan

**Branch:** `feature/semantic-nl2sql-srs`  
**Phase:** 1 — Inspection & Design (NO CODE CHANGES)  
**Date:** 2026-08-16  
**Git State:** Clean working tree, 5 commits on `main`, branch forked at `a4b5e43`

---

## A. CURRENT ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────┐
│                   FRONTEND  (Vite + React 19)               │
│                                                             │
│  src/App.jsx ─ Router + Clerk auth + MainLayout             │
│  ├── screens/DashboardScreen.jsx                            │
│  ├── screens/UploadScreen.jsx                               │
│  ├── screens/DictionaryScreen.jsx                           │
│  ├── screens/QualityScreen.jsx                              │
│  ├── screens/AnalysisScreen.jsx                             │
│  ├── screens/Visualization3D.jsx                            │
│  ├── screens/ChatScreen.jsx          ← full-page chat       │
│  ├── components/AIAssistantModal.jsx ← floating chat widget │
│  ├── components/PDFExportModal.jsx                          │
│  ├── components/DBViz3D.jsx / ERDiagram2D.jsx               │
│  └── store/useAppStore.js, useVisualizationStore.js         │
│                                                             │
│  API Client: src/api/axios.js (Axios instance)              │
│              src/api/api.js  (typed wrappers + retry)       │
└────────────────────────┬────────────────────────────────────┘
                         │  HTTP / JSON / SSE
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              BACKEND  (FastAPI, Backend/backend/)            │
│                                                             │
│  main.py (FastAPI app, all route handlers)                   │
│  ├── auth.py          → Clerk JWT validation / mock mode    │
│  ├── schema.py        → PRAGMA-based extraction + FK detect │
│  ├── intelligent_schema.py → stats, PK/FK inference, index  │
│  ├── quality.py       → health_score (completeness/fresh/   │
│  │                       consistency)                       │
│  ├── analysis.py      → numeric/categorical/date profiling  │
│  ├── llm.py           → Ollama client, all prompts,         │
│  │                       schema context builder,            │
│  │                       table relevance, SQL extraction     │
│  ├── new_llm_funcs.py → prompt_table_analysis only          │
│  ├── sql_runner.py    → read-only SQL exec, table extract   │
│  └── ingest_handler.py→ CSV/SQLite/ZIP file ingestion       │
│                                                             │
│  Database: database.sqlite (working SQLite file)            │
│  LLM:      Ollama @ 127.0.0.1:11434, model qwen3.5:4b      │
└─────────────────────────────────────────────────────────────┘
```

### Exact File Responsibilities

| File | Responsibility |
|------|---------------|
| [`main.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/main.py) | FastAPI app, all 16 route handlers, startup warmup, CORS, helper functions |
| [`llm.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/llm.py) | Ollama HTTP calls (`ask_llm`, `ask_llm_stream`), all prompt templates, `build_schema_context`, `get_relevant_tables`, `validate_sql_columns`, `extract_sql_clean`, `safe_sql_fallback`, `build_column_context`, `health_check` |
| [`schema.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/schema.py) | `extract_schema()`, `extract_relationships()`, PRAGMA-based column/FK extraction, implicit relationship detection, mermaid export |
| [`intelligent_schema.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/intelligent_schema.py) | `generate_intelligent_schema()`, column stat computation, PK/FK detection from data, index creation |
| [`quality.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/quality.py) | `compute_quality()` — health_score from completeness, freshness, consistency |
| [`analysis.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/analysis.py) | `compute_analysis()` — numeric stats, categorical entropy, date ranges, correlations |
| [`sql_runner.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/sql_runner.py) | `execute_read_only_sql()`, `extract_queried_tables()`, read-only enforcement |
| [`ingest_handler.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/ingest_handler.py) | `create_table_from_csv()`, `copy_sqlite_database()`, `process_zip_file()` |
| [`auth.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/auth.py) | `get_current_user()` — Clerk JWT validation or mock mode |
| [`new_llm_funcs.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/new_llm_funcs.py) | `prompt_table_analysis()` — single prompt template |

### All Existing API Endpoints (from `main.py`)

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| GET | `/` | `read_root` | Health ping |
| GET | `/health` | `health` | Lightweight health |
| GET | `/me` | `read_current_user` | Auth test |
| GET | `/schema` | `get_schema` | Full schema extraction |
| GET | `/relationships` | `get_relationships` | FK/inferred relationships |
| POST | `/chat` | `handle_nl_to_sql` | NL→SQL (non-streaming) |
| POST | `/query/stream` | `query_stream` | NL→SQL (SSE streaming) |
| POST | `/query` | `query_alias` | Alias → `/chat` |
| POST | `/table-reasoning` | `table_reasoning` | Table purpose explanation |
| POST | `/column-chat` | `column_chat` | Column-level Q&A |
| GET | `/health/llm` | `llm_health` | Ollama + model health |
| GET | `/quality/{table_name}` | `get_table_quality` | Single table quality |
| GET | `/quality` | `get_quality` | All tables quality summary |
| POST | `/graph-data` | `get_graph_data` | Combined schema+rel+quality |
| POST | `/api/generate-summary` | `generate_summary` | Executive summary generation |
| POST | `/ingest/clear` | `clear_database` | Wipe database |
| POST | `/ingest/file` | `ingest_file` | File upload handler |
| GET | `/analysis/{table_name}` | `get_table_analysis` | Statistical analysis |

---

## B. CURRENT NL-TO-SQL FLOW

### Non-Streaming Path (`POST /chat` and `POST /query`)

```
User types question in AIAssistantModal or ChatScreen
    │
    ▼
Frontend: postQueryPayload({ query: text })
    │  src/api/api.js → POST /query → main.py query_alias → handle_nl_to_sql
    ▼
main.py handle_nl_to_sql(payload: ChatRequest)                    [L209-L324]
    │
    ├─ 1. conn = get_working_conn()                               [L214]
    │     → sqlite3.connect("database.sqlite")                    [L121]
    │
    ├─ 2. relevant_tables = llm.get_relevant_tables(conn, query)  [L217]
    │     → llm.py get_relevant_tables()                          [L378-L413]
    │     → keyword term matching: splits query + table/column names
    │       into tokens, scores overlap, returns top MAX_RELEVANT_TABLES (6)
    │
    ├─ 3. schema_context = llm.build_schema_context(conn, table_names=relevant_tables) [L218]
    │     → llm.py build_schema_context()                         [L86-L127]
    │     → PRAGMA table_info, SELECT COUNT(*), SELECT * LIMIT 3
    │     → Formats: "TABLE name (N rows)\n  col TYPE [PK]; examples: ..."
    │     → Cached by (db_path, mtime, size, table_list)
    │
    ├─ 4. sql_prompt = llm.prompt_nl_to_sql(query, schema_context) [L221]
    │     → llm.py prompt_nl_to_sql()                             [L130-L152]
    │     → System: "You write one correct SQLite query..."
    │     → User: "SCHEMA:\n{context}\nUser question: ...\nWrite the query now:"
    │
    ├─ 5. sql = llm.ask_llm(sql_prompt, task="sql")               [L222]
    │     → llm.py ask_llm()                                      [L437-L454]
    │     → POST to Ollama /api/chat (temp=0.05, num_predict=120)
    │     → _prompt_messages parses <|system|>/<|user|> tokens → chat messages
    │
    ├─ 6. sql = llm.extract_sql_clean(sql)                        [L225]
    │     → llm.py extract_sql_clean()                            [L481-L502]
    │     → Strips control tokens, <think> blocks, markdown fences
    │     → Truncates at first semicolon, regex extracts SELECT/WITH
    │
    ├─ 7. is_valid, _ = llm.validate_sql_columns(sql, conn)       [L229]
    │     → llm.py validate_sql_columns()                         [L328-L360]
    │     → NOTE: Currently always returns (True, "") — conservative no-op
    │
    ├─ 8. execution = sql_runner.execute_read_only_sql(sql)        [L237]
    │     → sql_runner.py execute_read_only_sql()                 [L75-L138]
    │     → _normalize_sql → _is_read_only_sql check → sqlite3.execute
    │     → Returns {ok, error, rows, columns, row_count, truncated}
    │
    ├─ 9. IF execution fails → Self-healing (ONE attempt):
    │     │  fix_prompt = llm.prompt_fix_sql(sql, error, schema_context)  [L248]
    │     │  fixed_sql = llm.ask_llm(fix_prompt, task="fix_sql")         [L249]
    │     │  fixed_sql = llm.extract_sql_clean(fixed_sql)                [L250]
    │     │  execution = sql_runner.execute_read_only_sql(fixed_sql)     [L252]
    │     │
    │     └─ IF fix also fails → safe_sql_fallback(conn)                 [L263]
    │        → "SELECT * FROM {first_table} LIMIT 20;"
    │
    ├─ 10. natural_answer = _generate_natural_answer(...)          [L292]
    │      → llm.prompt_interpret_results() → llm.ask_llm(task="interpret")
    │      → Converts SQL output to plain English
    │
    └─ 11. Return JSON to frontend                                [L295-L308]
           {sql, explanation, natural_answer, data, columns,
            queried_tables, row_count, truncated, execution_ok,
            execution_error, used_fallback, reason}
```

### Streaming Path (`POST /query/stream`)

Same logic as above but uses `llm.ask_llm_stream()` and yields SSE events: `sql_chunk` → `execution_result` → `explanation_chunk` → `done`.

### Frontend Display

- [`AIAssistantModal.jsx`](file:///d:/SchemaSense/Schema_Sense-/src/components/AIAssistantModal.jsx): Floating widget, calls `postQueryPayload`, shows `natural_answer` + SQL + result table.
- [`ChatScreen.jsx`](file:///d:/SchemaSense/Schema_Sense-/src/screens/ChatScreen.jsx): Full-page chat, includes client-side retry logic (`shouldRetryWithClarifiedPrompt`), normalizes user questions (`normalizeUserQuestion`), highlights queried tables in 3D graph.

---

## C. EXISTING FUNCTIONALITY WE CAN REUSE

| Capability | Existing Function | File | Reuse Strategy |
|---|---|---|---|
| **Schema extraction** | `extract_schema()` | [`schema.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/schema.py#L172-L215) | Call directly to get table/column/PK/FK data for metadata generation |
| **Column stats** | `compute_column_stats()` | [`intelligent_schema.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/intelligent_schema.py#L5-L31) | Reuse null%, uniqueness per column |
| **PK detection** | `detect_primary_keys()` | [`intelligent_schema.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/intelligent_schema.py#L33-L100) | Reuse for metadata |
| **FK detection** | `detect_foreign_keys()` | [`intelligent_schema.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/intelligent_schema.py#L102-L186) | Reuse for metadata |
| **Relationship extraction** | `extract_relationships()` | [`schema.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/schema.py#L423-L486) | Reuse for metadata relationships |
| **Quality profiling** | `compute_quality()` | [`quality.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/quality.py#L11-L240) | Reuse health scores for metadata |
| **Statistical profiling** | `compute_analysis()` | [`analysis.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/analysis.py#L9-L162) | Reuse numeric/categorical/date stats for metadata evidence |
| **Schema context building** | `build_schema_context()` | [`llm.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/llm.py#L86-L127) | Reuse for prompt construction (sample rows) |
| **Column context** | `build_column_context()` | [`llm.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/llm.py#L569-L624) | Reuse top values/sample values for metadata |
| **Ollama call (sync)** | `ask_llm()` | [`llm.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/llm.py#L437-L454) | Reuse for all LLM calls |
| **Ollama call (stream)** | `ask_llm_stream()` | [`llm.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/llm.py#L457-L479) | Reuse for streaming responses |
| **SQL extraction** | `extract_sql_clean()` | [`llm.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/llm.py#L481-L502) | Reuse to clean LLM SQL output |
| **SQL execution** | `execute_read_only_sql()` | [`sql_runner.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/sql_runner.py#L75-L138) | Reuse as final execution step |
| **Table name extraction** | `extract_queried_tables()` | [`sql_runner.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/sql_runner.py#L21-L51) | Reuse for validation cross-checks |
| **Repair prompt** | `prompt_fix_sql()` | [`llm.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/llm.py#L155-L173) | Reuse within the self-correction loop |
| **Result interpretation** | `prompt_interpret_results()` | [`llm.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/llm.py#L191-L254) | Reuse for result explanation |
| **DB connection** | `get_working_conn()` | [`main.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/main.py#L120-L121) | Reuse (or replicate — it's a one-liner) |
| **Identifier quoting** | `_quote_identifier()` | Multiple files | Reuse for safe SQL identifiers |
| **Prompt message parsing** | `_prompt_messages()` | [`llm.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/llm.py#L422-L434) | Already used by ask_llm — transparent |
| **JSON extraction** | `extract_json_object()` | [`llm.py`](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/llm.py#L505-L536) | Reuse for parsing structured LLM output |

---

## D. PROPOSED MODULE DESIGN

### Module 1: `semantic_metadata.py`

**Path:** `Backend/backend/semantic_metadata.py`  
**Responsibility:** Generate and persist semantic metadata for all tables/columns in the active database.

| Item | Detail |
|---|---|
| **Inputs** | Active `database.sqlite` |
| **Outputs** | `Backend/backend/metadata_store.json` (written to disk) |
| **Reuses** | `schema.extract_schema()`, `quality.compute_quality()`, `analysis.compute_analysis()`, `llm.build_column_context()`, `llm.ask_llm()`, `llm.extract_json_object()` |
| **Dependencies** | None beyond existing |
| **API integration** | Called by new endpoint `POST /semantic/generate` and triggered after ingestion |

**Key functions:**
- `collect_table_evidence(table_name) → dict` — Aggregates schema, quality, analysis, sample values, relationships into a single evidence dict per table.
- `generate_table_metadata(table_name, evidence) → dict` — Calls Qwen3.5:4b with evidence to produce table description, column descriptions, semantic aliases, business meaning.
- `generate_all_metadata() → dict` — Iterates all tables, generates metadata, writes `metadata_store.json`.
- `load_metadata() → dict` — Reads `metadata_store.json` from disk.
- `get_metadata_age() → float | None` — Returns age of stored metadata in seconds.

---

### Module 2: `semantic_embeddings.py`

**Path:** `Backend/backend/semantic_embeddings.py`  
**Responsibility:** Generate embeddings from metadata and build/query a FAISS index.

| Item | Detail |
|---|---|
| **Inputs** | `metadata_store.json` contents |
| **Outputs** | FAISS IndexFlatIP in memory + persisted `.faiss` and `.json` mapping files |
| **Reuses** | `semantic_metadata.load_metadata()` |
| **Dependencies** | `sentence-transformers`, `faiss-cpu`, `numpy` |
| **API integration** | Called internally by the query pipeline; rebuild triggered with metadata generation |

**Key functions:**
- `_build_embedding_text(table_name, table_meta, column_name=None, column_meta=None) → str` — Converts a metadata entry into embeddable text.
- `build_index(metadata) → (faiss.IndexFlatIP, list[dict])` — Embeds all entries, L2-normalizes, builds IndexFlatIP, returns index + mapping list.
- `save_index(index, mapping, path)` / `load_index(path) → (index, mapping)` — Persistence.
- `retrieve(query_text, top_k=10) → list[dict]` — Embeds query, L2-normalizes, searches index, returns ranked metadata entries with scores.
- `get_or_build_index() → (index, mapping)` — Lazy-loads from disk or rebuilds if stale.

---

### Module 3: `semantic_pipeline.py`

**Path:** `Backend/backend/semantic_pipeline.py`  
**Responsibility:** Orchestrates the full semantic NL-to-SQL pipeline: retrieval → context → generation → validation → execution → correction → explanation.

| Item | Detail |
|---|---|
| **Inputs** | Natural language question (str) |
| **Outputs** | `dict` matching existing `/query` response contract |
| **Reuses** | `semantic_embeddings.retrieve()`, `llm.ask_llm()`, `llm.extract_sql_clean()`, `llm.prompt_fix_sql()`, `llm.prompt_interpret_results()`, `sql_runner.execute_read_only_sql()`, `sql_runner.extract_queried_tables()` |
| **Dependencies** | `sqlglot` |
| **API integration** | Called from enhanced `/chat` and `/query` endpoints in `main.py` |

**Key functions:**
- `build_semantic_context(retrieved_entries, conn) → str` — Combines retrieved semantic metadata with schema context into a structured prompt section.
- `generate_sql(question, semantic_context) → str` — Calls Qwen3.5:4b with a semantic-aware NL-to-SQL prompt.
- `validate_sql(sql) → (bool, list[str])` — Uses SQLGlot to parse, check read-only, validate tables/columns against schema.
- `execute_with_correction(question, sql, semantic_context, conn, max_retries=2) → dict` — Validates → executes → on error: repairs → re-validates → re-executes. Returns execution result dict.
- `explain_results(question, sql, columns, rows, row_count) → str` — Calls existing `prompt_interpret_results` + `ask_llm`.
- `run_pipeline(question) → dict` — Full orchestrator: retrieve → context → generate → validate → execute → correct → explain → return response.

---

### Module 4: `semantic_eval.py`

**Path:** `Backend/backend/semantic_eval.py`  
**Responsibility:** Evaluation and ablation support for the research pipeline.

| Item | Detail |
|---|---|
| **Inputs** | Test question sets, expected SQL / expected results |
| **Outputs** | Evaluation metrics (accuracy, correction rate, retrieval recall) |
| **Reuses** | `semantic_pipeline.run_pipeline()`, `sql_runner.execute_read_only_sql()` |
| **Dependencies** | `sqlglot` (for AST comparison) |
| **API integration** | Optional `POST /semantic/evaluate` endpoint |

**Key functions:**
- `evaluate_question(question, expected_sql=None, expected_result=None) → dict` — Runs pipeline, compares output.
- `run_evaluation_suite(test_cases) → dict` — Batch evaluation.
- `ablation_run(config_overrides, test_cases) → dict` — Runs pipeline with specific components disabled.

---

## E. DATA FLOWS

### FLOW 1 — Metadata Generation (triggered after database ingestion or on-demand)

```
database.sqlite
    │
    ├─ schema.extract_schema()
    │  → table names, column names, types, PKs, FKs, row counts,
    │    sample values, relationships, mermaid exports
    │
    ├─ quality.compute_quality(table_name) [per table]
    │  → health_score, completeness, freshness, consistency, orphans
    │
    ├─ analysis.compute_analysis(table_name) [per table]
    │  → numeric stats, categorical stats, date stats, correlations
    │
    ├─ llm.build_column_context(conn, table, col) [per column, sampled]
    │  → top values, sample values, null%, uniqueness%, FK references
    │
    └─ Aggregate into evidence dict per table
         │
         ▼
    semantic_metadata.generate_table_metadata(table_name, evidence)
         │
         ├─ Build LLM prompt with all evidence
         ├─ llm.ask_llm(prompt, task="summary")
         ├─ llm.extract_json_object(response)
         │
         └─ Returns: table description, column descriptions,
            semantic aliases, business meaning, data domain
         │
         ▼
    Write metadata_store.json
         │
         ▼
    semantic_embeddings.build_index(metadata)
         │
         ├─ For each table + each column:
         │    _build_embedding_text(table, table_meta, col, col_meta) → str
         │
         ├─ SentenceTransformer("all-MiniLM-L6-v2").encode(texts)
         ├─ L2-normalize all vectors
         ├─ faiss.IndexFlatIP(384)  ← 384-dim for MiniLM-L6-v2
         ├─ index.add(normalized_vectors)
         │
         └─ Save: metadata_index.faiss + metadata_mapping.json
```

### FLOW 2 — User Query (semantic NL-to-SQL)

```
User: "What is the average order value per customer?"
    │
    ▼
semantic_pipeline.run_pipeline(question)
    │
    ├─ 1. RETRIEVAL
    │  │  semantic_embeddings.retrieve(question, top_k=10)
    │  │    → SentenceTransformer.encode(question)
    │  │    → L2-normalize query vector
    │  │    → faiss_index.search(query_vector, k=10)
    │  │    → Return ranked metadata entries with cosine scores
    │  │
    │  └─ Output: list of {table, column?, description, aliases, score}
    │
    ├─ 2. CONTEXT CONSTRUCTION
    │  │  build_semantic_context(retrieved_entries, conn)
    │  │    → Deduplicate tables from retrieved entries
    │  │    → llm.build_schema_context(conn, table_names=unique_tables)
    │  │    → Merge: schema DDL + sample rows + semantic descriptions
    │  │
    │  └─ Output: enriched context string
    │
    ├─ 3. SQL GENERATION
    │  │  generate_sql(question, semantic_context)
    │  │    → Build semantic NL-to-SQL prompt (enhanced prompt_nl_to_sql)
    │  │    → llm.ask_llm(prompt, task="sql")
    │  │    → llm.extract_sql_clean(raw_sql)
    │  │
    │  └─ Output: cleaned SQL string
    │
    ├─ 4. SQLGLOT VALIDATION
    │  │  validate_sql(sql)
    │  │    → sqlglot.parse(sql, read="sqlite")
    │  │    → Check: is SELECT/WITH only, no forbidden statements
    │  │    → Check: all table names exist in database
    │  │    → Check: all column names exist in referenced tables
    │  │
    │  └─ Output: (is_valid: bool, errors: list[str])
    │
    ├─ 5. EXECUTION + CORRECTION LOOP (max 2 retries)
    │  │  execute_with_correction(question, sql, context, conn)
    │  │    │
    │  │    ├─ IF validation fails → repair prompt → re-validate → retry
    │  │    ├─ IF execution fails  → repair prompt → re-validate → retry
    │  │    └─ IF max retries exhausted → safe_sql_fallback(conn)
    │  │
    │  │  Each retry:
    │  │    → llm.prompt_fix_sql(sql, error, context)
    │  │    → llm.ask_llm(prompt, task="fix_sql")
    │  │    → llm.extract_sql_clean(fixed_sql)
    │  │    → validate_sql(fixed_sql)
    │  │    → sql_runner.execute_read_only_sql(fixed_sql)
    │  │
    │  └─ Output: execution result dict
    │
    ├─ 6. RESULT EXPLANATION
    │  │  explain_results(question, sql, columns, rows, row_count)
    │  │    → llm.prompt_interpret_results(...)
    │  │    → llm.ask_llm(prompt, task="interpret")
    │  │
    │  └─ Output: natural language answer string
    │
    └─ 7. RESPONSE
       │  Assemble response matching existing API contract:
       │  {sql, explanation, natural_answer, data, columns,
       │   queried_tables, row_count, truncated, execution_ok,
       │   execution_error, used_fallback, reason}
       │
       └─ Additional diagnostic fields:
          {retrieval_scores, validation_pass, correction_attempts,
           pipeline_version}
```

---

## F. METADATA JSON DESIGN

### Proposed `metadata_store.json` Structure

```json
{
  "version": "1.0.0",
  "generated_at": "2026-08-16T10:30:00Z",
  "generator": "semantic_metadata.py",
  "model": "qwen3.5:4b",
  "database_file": "database.sqlite",
  "database_mtime": 1723806600.0,
  "database_size_bytes": 13430784,
  "table_count": 9,

  "tables": {
    "olist_orders_dataset": {
      "observed": {
        "table_name": "olist_orders_dataset",
        "row_count": 99441,
        "column_count": 8,
        "columns": {
          "order_id": {
            "type": "TEXT",
            "is_pk": true,
            "is_fk": false,
            "nullable": false,
            "null_percentage": 0.0,
            "uniqueness": 100.0,
            "sample_values": ["e481f51cbdc54678b7cc49136f2d6af7", "..."],
            "top_values": [{"value": "...", "count": 1}]
          }
        },
        "relationships": [
          {
            "source_table": "olist_orders_dataset",
            "source_col": "customer_id",
            "target_table": "olist_customers_dataset",
            "target_col": "customer_id",
            "type": "inferred",
            "confidence": 0.97
          }
        ],
        "quality": {
          "health_score": 87,
          "completeness": 95,
          "freshness": 42,
          "consistency": 100
        },
        "statistics": {
          "numeric_columns": ["..."],
          "categorical_columns": ["..."],
          "date_columns": ["order_purchase_timestamp"],
          "correlation_pairs": []
        }
      },

      "generated": {
        "table_description": "This table records e-commerce purchase orders with timestamps tracking the order lifecycle from purchase to delivery.",
        "business_domain": "e-commerce",
        "semantic_aliases": ["orders", "purchases", "transactions"],
        "columns": {
          "order_id": {
            "description": "Unique identifier for each purchase order",
            "semantic_aliases": ["order identifier", "purchase ID"],
            "business_role": "primary_key"
          },
          "order_status": {
            "description": "Current fulfillment status of the order",
            "semantic_aliases": ["status", "order state", "fulfillment status"],
            "business_role": "categorical_status"
          }
        },
        "common_questions": [
          "How many orders are there?",
          "What is the distribution of order statuses?"
        ],
        "generated_at": "2026-08-16T10:30:00Z",
        "model": "qwen3.5:4b",
        "model_version": "qwen3.5:4b"
      }
    }
  }
}
```

### Key Design Principles

1. **`observed` vs `generated` separation** — Observed facts are deterministic and come from schema/profiling. Generated content comes from LLM and is labeled with provenance.
2. **Provenance fields** — `generated_at`, `model`, `version` at root and per-table `generated` section.
3. **Database fingerprint** — `database_mtime` and `database_size_bytes` allow staleness detection after re-ingestion.
4. **Flat JSON file** — Single `metadata_store.json` avoids database coupling. Easily diffable, versionable.

---

## G. FAISS DESIGN

### What Gets Embedded

Each embeddable unit is one of:

1. **Table-level entry** — Combines: table name, display name, table description, semantic aliases, business domain, column names list, relationship summaries.
2. **Column-level entry** — Combines: table name, column name, column description, column type, semantic aliases, business role, sample values, top values.

### How Metadata Becomes Embedding Text

```python
# Table-level embedding text
def _build_table_embedding_text(table_name, meta):
    gen = meta.get("generated", {})
    obs = meta.get("observed", {})
    aliases = ", ".join(gen.get("semantic_aliases", []))
    col_names = ", ".join(obs.get("columns", {}).keys())
    return (
        f"Table: {table_name}. "
        f"Description: {gen.get('table_description', '')}. "
        f"Also known as: {aliases}. "
        f"Domain: {gen.get('business_domain', '')}. "
        f"Columns: {col_names}."
    )

# Column-level embedding text
def _build_column_embedding_text(table_name, col_name, col_obs, col_gen):
    aliases = ", ".join(col_gen.get("semantic_aliases", []))
    samples = ", ".join(str(v) for v in (col_obs.get("sample_values", []))[:5])
    return (
        f"Column: {table_name}.{col_name}. "
        f"Type: {col_obs.get('type', '')}. "
        f"Description: {col_gen.get('description', '')}. "
        f"Also known as: {aliases}. "
        f"Sample values: {samples}."
    )
```

### Model & Normalization

- **Model:** `all-MiniLM-L6-v2` (384-dimensional output, pre-trained for semantic similarity)
- **Normalization:** L2-normalize every vector after encoding so that inner product = cosine similarity
- **Index type:** `faiss.IndexFlatIP` (exact inner product search; fast enough for < 10,000 entries typical in a database schema)

### Construction

```python
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

model = SentenceTransformer("all-MiniLM-L6-v2")
texts = [...]       # list of embedding texts
mapping = [...]     # parallel list of {table, column?, type: "table"|"column"}

vectors = model.encode(texts, normalize_embeddings=True)  # already L2-normalized
vectors = np.array(vectors, dtype="float32")

index = faiss.IndexFlatIP(384)
index.add(vectors)
```

### Vector-to-Metadata Mapping

A parallel `metadata_mapping.json` list maintains the correspondence:

```json
[
  {"type": "table", "table": "olist_orders_dataset", "idx": 0},
  {"type": "column", "table": "olist_orders_dataset", "column": "order_id", "idx": 1},
  ...
]
```

Index position `i` in FAISS → `mapping[i]` → lookup full metadata from `metadata_store.json`.

### Persistence

- `Backend/backend/metadata_index.faiss` — FAISS binary index file (`faiss.write_index`)
- `Backend/backend/metadata_mapping.json` — JSON mapping list
- Both are `.gitignore`d (generated artifacts)

### Rebuild Strategy

Rebuild is triggered when:
1. `POST /ingest/file` completes successfully (new data uploaded)
2. `POST /semantic/generate` is called explicitly
3. `metadata_store.json` `database_mtime` differs from current `database.sqlite` mtime

### Loading Strategy

- On first query: check if `metadata_index.faiss` + `metadata_mapping.json` exist on disk
- If yes and `metadata_store.json` `database_mtime` matches current DB → load from disk
- If stale or missing → rebuild from `metadata_store.json` (or generate metadata first if missing)
- Cache in module-level globals (single-process FastAPI with uvicorn reload)

### Top-k Retrieval

```python
def retrieve(query_text, top_k=10):
    query_vec = model.encode([query_text], normalize_embeddings=True)
    scores, indices = index.search(query_vec, top_k)
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        entry = mapping[idx].copy()
        entry["score"] = float(score)
        results.append(entry)
    return results
```

---

## H. SQL VALIDATION DESIGN

### SQLGlot Integration

#### Parsing
```python
import sqlglot

parsed = sqlglot.parse(sql, read="sqlite")
```
- `read="sqlite"` forces SQLite dialect interpretation.
- Returns a list of `Expression` objects (one per statement).

#### Read-Only Enforcement
```python
ALLOWED_STATEMENT_TYPES = {sqlglot.exp.Select}
# WITH (CTE) wraps a Select, so it's covered

for statement in parsed:
    if type(statement) not in ALLOWED_STATEMENT_TYPES:
        # REJECT: not a SELECT
```
- This replaces the current string-matching `_is_read_only_sql()` in `sql_runner.py` with AST-based enforcement.
- Catches edge cases the regex approach misses (e.g., `SELECT ... INTO`, subqueries containing `INSERT`).

#### Table Validation
```python
tables_in_sql = {t.name for t in statement.find_all(sqlglot.exp.Table)}
# Compare against actual tables from sqlite_master
valid_tables = set(get_table_names())
invalid = tables_in_sql - valid_tables
```

#### Column Validation
```python
columns_in_sql = {c.name for c in statement.find_all(sqlglot.exp.Column)}
# Compare against columns in referenced tables
for col in columns_in_sql:
    if col not in all_valid_columns_for_referenced_tables:
        # Flag as invalid
```
- This is a best-effort check. SQLGlot may not resolve all aliases, so validation errors are treated as warnings for the correction loop, not hard rejections.

#### Multiple Statement Handling
- If `sqlglot.parse()` returns more than 1 statement, reject. Only single-statement queries are allowed.

#### Unsafe Statement Detection
- Check parsed AST for `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `ATTACH`, `DETACH`, `PRAGMA` (write pragmas).

#### Validation Error Format
```python
def validate_sql(sql: str) -> tuple[bool, list[str]]:
    """Returns (is_valid, list_of_error_messages)"""
```

#### Interaction with Existing SQL Runner
- `validate_sql()` runs **before** `sql_runner.execute_read_only_sql()`.
- `sql_runner.execute_read_only_sql()` remains unchanged as the final execution gate.
- The existing `_is_read_only_sql()` in `sql_runner.py` is kept as a redundant safety layer — we do NOT remove it.

---

## I. SELF-CORRECTION DESIGN

### Current System (1-step)

```
main.py handle_nl_to_sql:
  generate SQL → execute → ON ERROR → prompt_fix_sql → execute fixed → ON ERROR → fallback
```

This exists in [`main.py` L245-L287](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/main.py#L245-L287).

### Proposed Extension (validation-aware bounded loop)

```
semantic_pipeline.execute_with_correction(question, sql, context, conn, max_retries=2):

  attempt = 0
  current_sql = sql
  errors = []

  LOOP (max_retries + 1 total attempts):
    │
    ├─ 1. validate_sql(current_sql)
    │     IF invalid:
    │       errors.append(validation_errors)
    │       → Skip execution, go to repair
    │
    ├─ 2. sql_runner.execute_read_only_sql(current_sql)
    │     IF ok:
    │       → RETURN success result
    │     IF error:
    │       errors.append(execution_error)
    │
    ├─ 3. IF attempt < max_retries:
    │       error_context = join(errors)
    │       fix_prompt = llm.prompt_fix_sql(current_sql, error_context, context)
    │       fixed_raw = llm.ask_llm(fix_prompt, task="fix_sql")
    │       current_sql = llm.extract_sql_clean(fixed_raw)
    │       attempt += 1
    │       → CONTINUE LOOP
    │
    └─ 4. IF all retries exhausted:
          fallback_sql = llm.safe_sql_fallback(conn)
          → RETURN fallback result with used_fallback=True
```

### Key Differences from Current System

1. **Validation before execution** — SQLGlot catches structural errors without hitting the database.
2. **Combined error context** — Both validation errors and execution errors are fed to the repair prompt.
3. **Configurable retry count** — Default 2 retries (3 total attempts), configurable for ablation.
4. **Existing `prompt_fix_sql` reused** — The existing repair prompt template in `llm.py` is reused directly.
5. **Existing `safe_sql_fallback` reused** — The existing fallback function is the last resort.

---

## J. API DESIGN

### Endpoints to Modify

| Endpoint | Modification |
|---|---|
| `POST /chat` (`handle_nl_to_sql`) | Add conditional: if `metadata_store.json` exists and FAISS index is loaded, route through `semantic_pipeline.run_pipeline()` instead of the current keyword-based flow. Preserve the existing flow as fallback if semantic pipeline is not available. |
| `POST /query/stream` (`query_stream`) | Same: conditionally use semantic pipeline for the SQL generation + validation step, then stream as before. |
| `POST /query` | Already an alias to `/chat` — no change needed. |
| `POST /ingest/file` (`ingest_file`) | After successful ingestion, optionally trigger metadata regeneration (async or synchronous flag). |

### New Endpoints Required

| Method | Path | Purpose | Necessity |
|---|---|---|---|
| `POST` | `/semantic/generate` | Trigger metadata generation + FAISS rebuild | **Required** — explicit control over when metadata is generated. |
| `GET` | `/semantic/status` | Return metadata age, table count, index size, staleness flag | **Required** — frontend needs to know if semantic features are available. |
| `POST` | `/semantic/evaluate` | Run evaluation suite | **Optional** — research use only, not needed for core functionality. |

### Endpoints NOT Added

- No separate `/semantic/query` endpoint. The semantic pipeline integrates transparently into the existing `/chat`/`/query` flow. This avoids frontend changes and maintains backward compatibility.

---

## K. DEPENDENCIES

### Current `requirements.txt`

```
fastapi==0.115.0
uvicorn==0.30.0
sqlalchemy==2.0.35
pandas==2.2.3
python-multipart==0.0.12
python-dotenv==1.0.1
requests==2.32.3
httpx==0.28.1
sentence-transformers==3.1.0    ← LISTED but NOT IMPORTED anywhere
umap-learn==0.5.7               ← LISTED but NOT IMPORTED anywhere
reportlab==4.2.5
pymysql==1.1.1
psycopg2-binary==2.9.10
kaggle==1.6.17
PyJWT==2.8.0
cryptography==42.0.5
```

### Packages to ADD

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `faiss-cpu` | `>=1.7.4` | FAISS IndexFlatIP vector index | New dependency |
| `sqlglot` | `>=20.0.0` | SQL parsing, AST validation, dialect checking | New dependency |
| `numpy` | (transitive) | Vector operations, L2 normalization | Already installed transitively via pandas/sentence-transformers |

### Packages Already Listed but Unused

| Package | Status | Action |
|---|---|---|
| `sentence-transformers==3.1.0` | Listed in requirements.txt, **not imported anywhere** in the codebase | Will be used for `all-MiniLM-L6-v2` — no need to add, just import |
| `umap-learn==0.5.7` | Listed, not imported | Not needed for this feature; leave as-is |
| `sqlalchemy==2.0.35` | Listed, not imported in backend code (raw sqlite3 used everywhere) | Not needed; leave as-is |
| `pymysql==1.1.1` | Listed, not imported | Not needed for SQLite-only; leave as-is |
| `psycopg2-binary==2.9.10` | Listed, not imported | Not needed for SQLite-only; leave as-is |
| `kaggle==1.6.17` | Listed, not imported | Not needed; leave as-is |

---

## L. IMPLEMENTATION ORDER

> [!IMPORTANT]
> Each phase is independently deployable and preserves the existing working system.

### Phase 2: Semantic Metadata Generation
1. Create `Backend/backend/semantic_metadata.py`
2. Implement evidence collection using existing `schema.py`, `quality.py`, `analysis.py`, `llm.py`
3. Implement LLM-based metadata generation prompts
4. Implement `metadata_store.json` read/write
5. Add `POST /semantic/generate` and `GET /semantic/status` endpoints to `main.py`
6. **Test:** Generate metadata for the existing database, verify JSON structure

### Phase 3: Embeddings & FAISS Index
1. Create `Backend/backend/semantic_embeddings.py`
2. Implement embedding text construction from metadata
3. Implement `all-MiniLM-L6-v2` encoding + L2 normalization
4. Implement FAISS `IndexFlatIP` build, save, load
5. Implement `retrieve()` function
6. Wire rebuild into `POST /semantic/generate`
7. Add `faiss-cpu` and `sqlglot` to `requirements.txt`
8. **Test:** Build index, run sample queries, verify retrieval quality

### Phase 4: SQLGlot Validation
1. Implement `validate_sql()` in `semantic_pipeline.py` (or a dedicated module)
2. Cover: parsing, read-only check, table/column validation, multi-statement rejection
3. **Test:** Validate against known good/bad SQL strings

### Phase 5: Semantic NL-to-SQL Pipeline
1. Create `Backend/backend/semantic_pipeline.py`
2. Implement `build_semantic_context()` — merge retrieved metadata + schema context
3. Implement `generate_sql()` — enhanced prompt with semantic context
4. Implement `execute_with_correction()` — validation + execution + bounded correction loop
5. Implement `explain_results()` — reuse existing `prompt_interpret_results`
6. Implement `run_pipeline()` — full orchestrator
7. **Test:** End-to-end with sample questions

### Phase 6: Integration into Existing Endpoints
1. Modify `handle_nl_to_sql` in `main.py` to conditionally use `semantic_pipeline.run_pipeline()` when metadata/index are available
2. Modify `query_stream` similarly for the streaming path
3. Optionally trigger metadata rebuild after `POST /ingest/file`
4. **Test:** Full frontend-to-backend flow, verify backward compatibility

### Phase 7: Evaluation Framework
1. Create `Backend/backend/semantic_eval.py`
2. Implement evaluation and ablation functions
3. Add optional `POST /semantic/evaluate` endpoint
4. **Test:** Run evaluation against test question sets

---

## M. RISKS

### Architecture Conflicts

| Risk | Impact | Mitigation |
|---|---|---|
| **Dual NL-to-SQL paths** — existing keyword path and new semantic path coexist | Behavioral inconsistency between paths | Conditional routing: use semantic if index available, fall back to keyword. Eventually deprecate keyword path. |
| **`validate_sql_columns` is a no-op** — existing function at [`llm.py` L328-L360](file:///d:/SchemaSense/Schema_Sense-/Backend/backend/llm.py#L328-L360) always returns `(True, "")` | No conflict, but wasted call | Replace usage with SQLGlot validation in the semantic path. Keep the old function for backward compatibility in the non-semantic path. |

### Duplicate Logic

| Risk | Mitigation |
|---|---|
| `_is_read_only_sql()` in `sql_runner.py` vs SQLGlot read-only check | Keep both. SQLGlot validates before execution; `sql_runner` is the defense-in-depth layer. |
| `get_relevant_tables()` keyword matching vs FAISS retrieval | FAISS replaces keyword matching in the semantic path. Keyword path stays for fallback. |
| Schema context building in `llm.build_schema_context()` vs `semantic_pipeline.build_semantic_context()` | Semantic context calls `build_schema_context()` internally and enriches it. No duplication. |

### Breaking Changes

| Risk | Impact | Mitigation |
|---|---|---|
| Response contract changes | Frontend expects exact `{sql, explanation, natural_answer, data, ...}` shape | Semantic pipeline returns the exact same response shape. Additional diagnostic fields are additive only. |
| Startup latency from loading `all-MiniLM-L6-v2` | First request delay | Lazy-load model on first query, not on FastAPI startup. Or add to existing `startup_event` warmup thread. |
| `metadata_store.json` size for large schemas | Disk I/O | For typical databases (<100 tables), JSON will be <1MB. Not a concern. |

### Metadata Staleness

| Risk | Mitigation |
|---|---|
| User uploads new data but doesn't regenerate metadata | Compare `database_mtime` in metadata vs current file. Warn via `/semantic/status`. Optionally auto-regenerate after ingestion. |
| LLM generates incorrect descriptions | Separate `observed` vs `generated` in JSON. Observed data is ground truth. Generated data is advisory. |

### LLM Failures

| Risk | Mitigation |
|---|---|
| Ollama unreachable or model not loaded | Existing `health_check()` already detects this. Semantic pipeline falls back to keyword-based flow. |
| LLM generates malformed JSON for metadata | `llm.extract_json_object()` already handles this with fallback. Metadata generation retries or uses deterministic fallback descriptions. |

### FAISS Failures

| Risk | Mitigation |
|---|---|
| Index file corrupted or missing | `get_or_build_index()` rebuilds from `metadata_store.json` if load fails. |
| `sentence-transformers` model download fails on first use | Document model pre-download in setup instructions. Model is ~80MB. |

### SQL Validation Bypasses

| Risk | Mitigation |
|---|---|
| SQLGlot fails to parse valid SQLite | Treat parse failure as validation pass (conservative). Let `sql_runner` be the final gate. |
| SQLGlot incorrectly rejects valid SQLite syntax | Use `read="sqlite"` dialect. If persistent, add to a known-exceptions allowlist. |

### SQLite Limitations

| Risk | Mitigation |
|---|---|
| No stored procedures, limited date functions | Prompts already specify SQLite syntax (`strftime`). Semantic prompts will reinforce this. |
| Concurrent writes during metadata generation | `metadata_store.json` is written atomically (write to temp file, rename). FAISS index rebuild is atomic. |

### Frontend/API Compatibility

| Risk | Mitigation |
|---|---|
| Frontend sends `system_context` and `screen` in `postQueryPayload` (see [`AIAssistantModal.jsx` L87-L91](file:///d:/SchemaSense/Schema_Sense-/src/components/AIAssistantModal.jsx#L87-L91)) but backend `ChatRequest` model ignores extra fields | No conflict — Pydantic ignores extra fields by default. |
| Frontend retry logic (`shouldRetryWithClarifiedPrompt` in [`ChatScreen.jsx` L24-L38](file:///d:/SchemaSense/Schema_Sense-/src/screens/ChatScreen.jsx#L24-L38)) may interfere with semantic pipeline | No conflict — retry is frontend-side. It just resends. The semantic pipeline handles each request independently. |

---

## N. FILE CHANGE PLAN

| Phase | New Files | Modified Files | Purpose |
|---|---|---|---|
| **Phase 2** | `Backend/backend/semantic_metadata.py` | `Backend/backend/main.py` (add 2 endpoints) | Semantic metadata generation, evidence collection, LLM enrichment, JSON persistence |
| **Phase 3** | `Backend/backend/semantic_embeddings.py` | `Backend/backend/requirements.txt` (add `faiss-cpu`, `sqlglot`), `Backend/backend/.gitignore` (add `*.faiss`, `metadata_*.json`) | Embedding generation, FAISS index build/load/query, persistence |
| **Phase 4** | *(within `semantic_pipeline.py`)* | — | SQLGlot validation function |
| **Phase 5** | `Backend/backend/semantic_pipeline.py` | — | Full semantic NL-to-SQL orchestration pipeline |
| **Phase 6** | — | `Backend/backend/main.py` (modify `handle_nl_to_sql`, `query_stream`, `ingest_file`) | Integrate semantic pipeline into existing endpoints |
| **Phase 7** | `Backend/backend/semantic_eval.py` | `Backend/backend/main.py` (add 1 optional endpoint) | Evaluation framework, ablation support |

### Summary of Changes

- **New files:** 4 (`semantic_metadata.py`, `semantic_embeddings.py`, `semantic_pipeline.py`, `semantic_eval.py`)
- **Modified files:** 2 (`main.py`, `requirements.txt`) + minor `.gitignore` update
- **Generated artifacts (not in git):** `metadata_store.json`, `metadata_index.faiss`, `metadata_mapping.json`
- **Frontend files modified:** 0 (all changes are backend-only; response contract is preserved)
- **Existing backend modules modified:** 0 (`llm.py`, `schema.py`, `quality.py`, `analysis.py`, `sql_runner.py`, `auth.py` — all untouched)

---

> [!IMPORTANT]
> This plan is designed to be **strictly additive**. No existing functionality is removed or broken. The semantic pipeline is a parallel path that activates only when metadata and FAISS index are available. All existing endpoints, prompts, and behaviors are preserved as-is.
