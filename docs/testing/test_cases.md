# SchemaSense Test Case Catalogue

This document provides a concise, structured catalogue of the 95 test cases and scenarios implemented and executed across the 10 test suites of SchemaSense AI.

---

## Suite 1: Semantic Metadata Extraction & Profiling
**Source:** `test_semantic_metadata.py` (9 tests)

| Test ID | Component | Purpose | Input / Scenario | Expected Behavior | Observed Result | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| `TC-META-01` | `semantic_metadata` | Multi-table evidence profiling | 5-table SQLite DB (`surveys`, `questions`, `responses`, `settings`, `audit_logs`) | Correctly extracts schema, primary keys, foreign keys, row counts, and column statistics. | Evidence dictionary populated accurately; row counts and PKs identified. | PASS |
| `TC-META-02` | `semantic_metadata` | Empty table handling | Table with 0 rows (`audit_logs`) | Gracefully profiles 0 rows without division by zero; empty sample values. | Row count is 0; sample values empty; no errors. | PASS |
| `TC-META-03` | `semantic_metadata` | Null-heavy and numeric columns | Column with 80%+ nulls (`notes`) and floats (`score`) | Correctly calculates `null_percentage` and collects valid sample values. | Null percentage accurately computed; types preserved. | PASS |
| `TC-META-04` | `semantic_metadata` | Deterministic fallback profiling | `use_llm=False` fallback generation | Generates rule-based aliases, business roles, and default questions. | Fallback metadata generated with `source="fallback"`. | PASS |
| `TC-META-05` | `semantic_metadata` | LLM metadata enrichment (mock) | Valid LLM JSON output | Enriches table description, semantic aliases, and business roles. | Structured LLM response parsed and assigned with `source="llm"`. | PASS |
| `TC-META-06` | `semantic_metadata` | LLM malformed JSON resilience | Invalid/corrupted string from LLM | Safely catches JSON error and falls back to deterministic metadata. | Fallback triggered without exception; `source="fallback"`. | PASS |
| `TC-META-07` | `semantic_metadata` | Atomic file write and load | Full generation on 5 tables | Atomically saves `metadata_store.json` and loads without data loss. | File written atomically, valid JSON loaded, fingerprint matches. | PASS |
| `TC-META-08` | `semantic_metadata` | Database staleness detection | Altering DB schema via `CREATE TABLE` | Flags metadata as stale based on SQLite fingerprint change (`mtime`/size). | `is_metadata_stale()` returns `True` immediately upon DB change. | PASS |
| `TC-META-09` | `semantic_metadata` / API | HTTP semantic status and generate | Calls `GET /semantic/status` and `POST /semantic/generate` | Returns status JSON, triggers metadata build, verifies existence. | HTTP 200 returned; metadata updated; status reflects fresh state. | PASS |

---

## Suite 2: FAISS Vector Embeddings & Similarity Retrieval
**Source:** `test_semantic_embeddings.py` (7 tests)

| Test ID | Component | Purpose | Input / Scenario | Expected Behavior | Observed Result | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| `TC-EMB-01` | `semantic_embeddings` | Embedding model & dimensions | Local `all-MiniLM-L6-v2` encoder | Produces 384-dimensional dense vectors with unit $L_2$ norm. | Vectors have shape (N, 384) and norm $1.0 \pm 10^{-5}$. | PASS |
| `TC-EMB-02` | `semantic_embeddings` | Semantic corpus construction | Rich metadata dictionary with 2 tables | Builds structured natural language documents for tables and columns. | 8 corpus documents built with correct prefix tagging. | PASS |
| `TC-EMB-03` | `semantic_embeddings` | Index building & types | 8 corpus vectors | Constructs `faiss.IndexFlatIP` index with exact vector count. | Index dimension 384; `ntotal == 8`; flat inner product verified. | PASS |
| `TC-EMB-04` | `semantic_embeddings` | Index save, load & staleness | Serialize and reload `.faiss`, `_mapping.json`, `_meta.json` | Persists vector index and restores mapping; tracks staleness vs DB. | Index and mapping restored identically; staleness correctly flagged. | PASS |
| `TC-EMB-05` | `semantic_embeddings` | Retrieval ranking and scores | Query: "customer locations and cities" | Ranks `Customers.city` and `Customers` highest with cosine scores. | Top result matches expected table/column; scores $\in [0, 1]$. | PASS |
| `TC-EMB-06` | `semantic_embeddings` | Edge cases & degenerate inputs | $top\_k \le 0$, empty strings, $top\_k > N$, empty metadata | Returns empty list or capped results without raising exceptions. | Handled gracefully without crash; returns empty or capped lists. | PASS |
| `TC-EMB-07` | `semantic_embeddings` | Rebuild and replace index | Add `Products` table to metadata and call `rebuild_index()` | Atomically replaces in-memory and on-disk index with new count (10). | Vector count updated to 10; `is_stale` returns `False`. | PASS |

---

## Suite 3: NL2SQL Context Construction & Prompting
**Source:** `test_nl2sql.py` (10 tests)

| Test ID | Component | Purpose | Input / Scenario | Expected Behavior | Observed Result | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| `TC-NL2SQL-01` | `nl2sql` | Context expansion & relationships | Query retrieved `Questions` table | Automatically includes foreign key related tables (`Surveys`). | Related tables expanded into prompt context. | PASS |
| `TC-NL2SQL-02` | `nl2sql` | Prompt builder structure | Context with retrieved tables/columns | Formats system prompt, SQLite dialect rules, schema, and question. | Well-formed prompt generated respecting token and schema constraints. | PASS |
| `TC-NL2SQL-03` | `nl2sql` | SQL response parsing | JSON string, markdown code blocks, raw SQL | Robustly extracts raw SQL string and cleans markdown formatting. | SQL query extracted cleanly across all output variations. | PASS |
| `TC-NL2SQL-04` | `nl2sql` | Count query generation | Question: "How many surveys?" | Constructs valid counting SQL candidate. | Valid SQL count statement produced. | PASS |
| `TC-NL2SQL-05` | `nl2sql` | Aggregation & filtering | Question: "Active surveys created in 2026" | Incorporates `WHERE is_active = 1` and date filters. | Query correctly targets active filters and conditions. | PASS |
| `TC-NL2SQL-06` | `nl2sql` | Multi-table JOIN query | Question: "Questions with survey title" | Constructs `INNER JOIN` on foreign key relationship. | Accurate `JOIN ... ON` query generated matching schema. | PASS |
| `TC-NL2SQL-07` | `nl2sql` | Semantic alias retrieval trigger | Query uses alias: "questionnaire" | FAISS retrieves `surveys` table via semantic alias match. | `Surveys` retrieved successfully based on semantic vector similarity. | PASS |
| `TC-NL2SQL-08` | `nl2sql` | Empty question validation | Empty string / whitespace question | Raises validation error / returns HTTP 400 Bad Request. | Caught by input validation; 400 status returned. | PASS |
| `TC-NL2SQL-09` | `nl2sql` | LLM failure handling | LLM raises exception or timeout | Propagates `RuntimeError` with clear diagnostic message. | RuntimeError caught and reported gracefully. | PASS |
| `TC-NL2SQL-10` | `nl2sql` / API | POST `/nl2sql/generate` endpoint | HTTP POST with question | Returns JSON with status, SQL, context, and retrieval metrics. | Status 200, valid response structure returned. | PASS |

---

## Suite 4: SQLGlot AST Safety & Validation
**Source:** `test_sql_validator.py` (16 tests / checks)

| Test ID | Component | Purpose | Input / Scenario | Expected Behavior | Observed Result | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| `TC-VAL-01` | `sql_validator` | Valid analytical query forms | 7 queries: SELECT, WHERE, GROUP BY, ORDER BY, JOIN, CTE, Subquery | Validates all read-only SQL patterns as `valid=True, read_only=True`. | All 7 analytical patterns validated successfully. | PASS |
| `TC-VAL-02` | `sql_validator` | Syntax error rejection | Malformed SQL: `SELECT FROM WHERE` | Identifies syntax error, returns `syntax_valid=False`. | Syntax error flagged with position and error code. | PASS |
| `TC-VAL-03` | `sql_validator` | Unknown table rejection | `SELECT * FROM nonexistent_table` | Flags table as unknown against active schema whitelist. | Rejected with `TABLE_NOT_FOUND` error. | PASS |
| `TC-VAL-04` | `sql_validator` | Unknown column rejection | `SELECT non_col FROM Survey` | Flags column as unknown against active schema whitelist. | Rejected with `COLUMN_NOT_FOUND` error. | PASS |
| `TC-VAL-05` | `sql_validator` | Mutation rejection: DROP | `DROP TABLE Survey;` | Identifies destructive command and rejects as unsafe. | Blocked: `MUTATION_NOT_ALLOWED`. | PASS |
| `TC-VAL-06` | `sql_validator` | Mutation rejection: DELETE | `DELETE FROM Answer WHERE answerid = 1;` | Identifies destructive command and rejects as unsafe. | Blocked: `MUTATION_NOT_ALLOWED`. | PASS |
| `TC-VAL-07` | `sql_validator` | Mutation rejection: UPDATE | `UPDATE Survey SET description = 'x';` | Identifies mutating command and rejects as unsafe. | Blocked: `MUTATION_NOT_ALLOWED`. | PASS |
| `TC-VAL-08` | `sql_validator` | Mutation rejection: INSERT | `INSERT INTO Survey VALUES (1, 'test');` | Identifies mutating command and rejects as unsafe. | Blocked: `MUTATION_NOT_ALLOWED`. | PASS |
| `TC-VAL-09` | `sql_validator` | Mutation rejection: ALTER | `ALTER TABLE Survey ADD COLUMN x INT;` | Identifies schema mutation and rejects. | Blocked: `MUTATION_NOT_ALLOWED`. | PASS |
| `TC-VAL-010` | `sql_validator` | Mutation rejection: CREATE | `CREATE TABLE hacker (id INT);` | Identifies DDL statement and rejects. | Blocked: `MUTATION_NOT_ALLOWED`. | PASS |
| `TC-VAL-011` | `sql_validator` | Command rejection: PRAGMA | `PRAGMA table_info(Survey);` | Rejects administrative command. | Blocked: `FORBIDDEN_OPERATION`. | PASS |
| `TC-VAL-012` | `sql_validator` | Command rejection: VACUUM | `VACUUM;` | Rejects administrative maintenance command. | Blocked: `FORBIDDEN_OPERATION`. | PASS |
| `TC-VAL-013` | `sql_validator` | Multi-statement injection | `SELECT COUNT(*) FROM Survey; DROP TABLE Answer;` | Detects multiple statements and rejects immediately. | Blocked: `MULTIPLE_STATEMENTS_ERROR`. | PASS |
| `TC-VAL-014` | `sql_validator` | Comment obfuscation attack | `SELECT * FROM Survey; /* comment */ DROP TABLE Answer;` | Strips comments, parses full AST, detects chained mutation. | Blocked: `MULTIPLE_STATEMENTS_ERROR`. | PASS |
| `TC-VAL-015` | `sql_validator` | Harmless comment validation | `SELECT /* valid comment */ COUNT(*) FROM Survey;` | Accepts harmless inline comments on valid single SELECT. | Validated successfully with `valid=True`. | PASS |
| `TC-VAL-016` | `sql_validator` | Phase 4 candidate queries | 5 real SQL candidates from prior phase | Confirms all 5 pass AST validation against the live schema. | All 5 candidates validated as valid and read-only. | PASS |

---

## Suite 5: Validated Execution & Bounded Self-Correction
**Source:** `test_nl2sql_execution.py` (7 tests)

| Test ID | Component | Purpose | Input / Scenario | Expected Behavior | Observed Result | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| `TC-EXEC-01` | `nl2sql` / `sql_runner` | Valid execution flow | Valid SELECT on test database | Validates AST, executes on SQLite, returns structured rows. | Execution succeeds with row count and elapsed time. | PASS |
| `TC-EXEC-02` | `nl2sql` / self-correction | Pre-execution AST correction | Attempt 0 produces unknown column; Attempt 1 fixes column | Validator catches error; error feedback triggers self-correction repair. | Repaired on attempt 1 (`retry_count=1`); execution succeeds. | PASS |
| `TC-EXEC-03` | `nl2sql` / self-correction | SQLite execution error correction | Attempt 0 fails SQLite execution; Attempt 1 fixes syntax | Captures SQLite operational error and repairs query. | Repaired and executed successfully. | PASS |
| `TC-EXEC-04` | `nl2sql` / retry bounds | Retry limit exhaustion | Faulty candidate repeated for 3 attempts (`max_retries=2`) | Exhausts retry budget and returns structured failure without looping. | Terminates cleanly at attempt 2; status="error". | PASS |
| `TC-EXEC-05` | `nl2sql` / security | Malicious self-correction rejection | Correction attempt introduces `DROP TABLE` | SQLGlot catches injected DDL during retry validation. | Malicious attempt rejected; database remains intact. | PASS |
| `TC-EXEC-06` | `nl2sql` / execution | JOIN and aggregation formatting | Multi-table join with `COUNT()` and `GROUP BY` | Formats results as structured JSON list of dicts. | Rows formatted with expected column headers and counts. | PASS |
| `TC-EXEC-07` | `nl2sql` / API | POST `/nl2sql/query` endpoint | End-to-end HTTP request with question | Returns validation, execution, rows, attempts, and explanation. | HTTP 200, complete query lifecycle payload returned. | PASS |

---

## Suite 6: Dataset Lifecycle & Synchronization
**Source:** `test_dataset_lifecycle.py` (10 tests)

| Test ID | Component | Purpose | Input / Scenario | Expected Behavior | Observed Result | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| `TC-LIFE-01` | `semantic_embeddings` | Initial dataset & staleness | Initial Survey schema replaced by Planets schema | Replaced SQLite DB immediately flags metadata as stale. | Invalidation triggered; staleness detected. | PASS |
| `TC-LIFE-02` | `semantic_embeddings` | Cascading synchronization | Sync Planets DB to metadata & FAISS | Invalidate caches; rebuild metadata & FAISS; verify 0 survey items. | Fresh index created; 0 survey entities returned. | PASS |
| `TC-LIFE-03` | `semantic_metadata` / API | Ingest clear endpoint | Call `POST /ingest/clear` | Wipes SQLite tables and deletes on-disk metadata and index files. | Status reflects `metadata_exists=False`, table count 0. | PASS |
| `TC-LIFE-04` | `semantic_embeddings` | Failure safety & cleanup | Simulate build failure during sync | Stale index artifacts removed to avoid serving mismatched schema. | Stale index removed safely; no corrupt artifacts retained. | PASS |
| `TC-LIFE-05` | `semantic_embeddings` | Sequential replacements | Survey $\to$ Planets $\to$ Books $\to$ Airports | Each replacement synchronously purges previous schema artifacts. | Every transition cleanly synchronized without residual tokens. | PASS |
| `TC-LIFE-06` | `nl2sql` / lifecycle | NL2SQL regression on switch | Query new dataset after replacement | NL2SQL prompt and queries contain only new schema elements. | Queries target exclusively new schema tables and columns. | PASS |
| `TC-LIFE-07` | `ingest_handler` / API | Upload API sync lifecycle | Upload CSV via `POST /ingest/file?clear=True` | API triggers cascading sync in-request. | Response returns `semantic_sync.status="synchronized"`. | PASS |
| `TC-LIFE-08` | `ingest_handler` / API | ZIP and SQLite file ingestion | Ingest multi-table ZIP and SQLite files | Synchronizes multiple tables simultaneously into vector index. | Multi-table schema synchronized into FAISS. | PASS |
| `TC-LIFE-09` | `semantic_embeddings` | Reverse dataset replacement | Switch back to previously used schema ($A \to B \to A$) | Cleanly reinstates original schema without contamination from $B$. | Schema $A$ restored with 0 residual items from $B$. | PASS |
| `TC-LIFE-10` | `semantic_embeddings` | Invariant checks across domains | 4 distinct datasets tested sequentially | Retrieved tables and columns are strict subsets of active DB. | Retrievability invariant verified across all test runs. | PASS |

---

## Suite 7: Cross-Dataset Independence & Schema Isolation
**Source:** `test_dataset_independence.py` (5 tests)

| Test ID | Component | Purpose | Input / Scenario | Expected Behavior | Observed Result | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| `TC-INDEP-01` | Full Pipeline | Dataset A: ENJOYSPORT | Meteorological single-table dataset | Ingest, profile, index, retrieve, execute count and filter queries. | All queries validated and executed; ground truth matches. | PASS |
| `TC-INDEP-02` | Full Pipeline | Dataset B: Customers & Orders | E-commerce multi-table relational schema | In-place replacement; verify 0 ENJOYSPORT entities; test JOIN queries. | E-commerce queries execute; 0% ENJOYSPORT entity leakage. | PASS |
| `TC-INDEP-03` | Full Pipeline | Dataset C: Employees & Depts | Enterprise HR multi-table relational schema | In-place replacement; verify 0 Customers/Orders entities; test aggregations. | HR queries execute; 0% prior entity leakage. | PASS |
| `TC-INDEP-04` | Ingestion / Cache | Sequential replacement cache sync | Rapid in-place sequential switching ($A \to B \to C$) | In-memory cache invalidated each cycle; fingerprint changes tracked. | Fingerprint and vector mappings update cleanly on each switch. | PASS |
| `TC-INDEP-05` | Security / Correction | Self-correction and attack rejection | Injection attacks and invalid columns on active DB | Injections rejected by validator; invalid column repaired by retry loop. | Injections blocked; retry repaired query; data remains intact. | PASS |

---

## Suite 8: Multi-Dataset Ground Truth Evaluation
**Source:** `test_nl2sql_multidataset.py` (17 tests)

| Test ID | Domain | Query Purpose | Scenario | Ground Truth Verification | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| `TC-MULTI-01` | E-Commerce | Simple Count | "How many customers are there?" | Count matches exact row count (4). | PASS |
| `TC-MULTI-02` | E-Commerce | Filtered Selection | "List products with price greater than 50" | Returns exact filtered product rows. | PASS |
| `TC-MULTI-03` | E-Commerce | Grouped Aggregation | "Total order amount per customer" | Multi-table JOIN and `SUM()` matches expected sums. | PASS |
| `TC-MULTI-04` | E-Commerce | Top-N Sorting | "Top 2 most expensive products" | `ORDER BY price DESC LIMIT 2` matches top products. | PASS |
| `TC-MULTI-05` | HR / Enterprise | Simple Count | "How many employees are there?" | Count matches exact employee rows (5). | PASS |
| `TC-MULTI-06` | HR / Enterprise | Average Calculation | "Average salary across all employees" | `AVG(salary)` matches ground truth average. | PASS |
| `TC-MULTI-07` | HR / Enterprise | Relational Join | "List employees with department name" | `INNER JOIN` on `dept_id` matches all mappings. | PASS |
| `TC-MULTI-08` | HR / Enterprise | Filtered Aggregation | "Departments with more than 1 employee" | `GROUP BY ... HAVING COUNT(*) > 1` verified. | PASS |
| `TC-MULTI-09` | Movies | Simple Count | "How many movies are in the database?" | Count matches exact movie rows (4). | PASS |
| `TC-MULTI-10` | Movies | Join Filtering | "Movies starring Leonardo DiCaprio" | `JOIN actors` with string filter matches film list. | PASS |
| `TC-MULTI-11` | Movies | Aggregated Ranking | "Highest rated movie" | `JOIN ratings` with `AVG(rating) DESC LIMIT 1` verified. | PASS |
| `TC-MULTI-12` | Movies | Filtered Comparison | "Movies released after 2010" | `WHERE release_year > 2010` matches exact records. | PASS |
| `TC-MULTI-13` | Meteorology | Simple Count | "How many weather stations are recorded?" | Count matches exact station rows (3). | PASS |
| `TC-MULTI-14` | Meteorology | Max Value Aggregation | "Highest recorded temperature" | `MAX(temperature)` matches extreme reading. | PASS |
| `TC-MULTI-15` | Meteorology | Multi-Table Average | "Average rainfall by station name" | `JOIN stations` with `AVG(rainfall)` grouped matches. | PASS |
| `TC-MULTI-16` | Meteorology | Date Range Filter | "Readings recorded on 2026-08-01" | Date comparison filter matches ground truth rows. | PASS |
| `TC-MULTI-17` | Self-Correction | Fault Injected Repair | Initial query has invalid column syntax | Repair loop produces valid SQL on retry 1; rows verified. | PASS |

---

## Suite 9: Full Dataset Lifecycle & Invariants
**Source:** `test_full_dataset_lifecycle.py` (8 tests)

| Test ID | Phase | Purpose | Scenario | Observed Behavior | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| `TC-FULL-01` | Phase B/C | Lifecycle switching | Sequential replacement of E-Commerce by HR | Caches flushed; FAISS index rebuilt; 0 cross-schema leakage. | PASS |
| `TC-FULL-02` | Phase D | Cache invalidation | Direct DB modification check | Memory cache flags stale when on-disk DB changes. | PASS |
| `TC-FULL-03` | Phase E | Staleness matrix | Multiple mutation combinations (mtime, size, table count) | All permutations accurately detected by fingerprint. | PASS |
| `TC-FULL-04` | Phase F | Ingestion failure safety | Simulated write failure | Stale vector index deleted to prevent serving mismatched schema. | PASS |
| `TC-FULL-05` | Phase H | Self-correction & security | Malicious DDL attack injection | AST validator intercepts commands; DB data unharmed. | PASS |
| `TC-FULL-06` | Phase I | Retry limits | Permanent syntax error simulation | Terminates at retry limit without infinite recursion. | PASS |
| `TC-FULL-07` | Phase J | API endpoints | HTTP `/ingest/file`, `/clear`, `/nl2sql/query` | Complete HTTP endpoint contract verified. | PASS |
| `TC-FULL-08` | Phase K | FAISS environment | Native FAISS `IndexFlatIP(384)` verification | L2 norm, dimensionality, and vector counts verified. | PASS |

---

## Suite 10: Live HTTP End-to-End Switching Flow
**Source:** `test_e2e_switching_flow.py` (6 tests / steps)

| Test ID | Step | Action | Scenario | Verified Outcome | Status |
| :--- | :---: | :--- | :--- | :--- | :---: |
| `TC-E2E-01` | 1 | Upload Dataset A | Ingest `books.csv` via HTTP | Synchronized; query `COUNT(*)` returns 2 books. | PASS |
| `TC-E2E-02` | 2 | Switch to Dataset B | Ingest `airports.csv` without server restart | Synchronized; query returns 2 airports; 0% books leakage. | PASS |
| `TC-E2E-03` | 3 | Switch to Dataset C | Ingest `planets.csv` without server restart | Synchronized; query returns 3 planets; 0% prior leakage. | PASS |
| `TC-E2E-04` | 4 | Reverse Switch to A | Re-ingest `books.csv` | Synchronized; books restored; 0% planets/airports leakage. | PASS |
| `TC-E2E-05` | 5 | Clear Dataset | Call `POST /ingest/clear` | Database tables dropped; metadata & FAISS removed; clean state. | PASS |
| `TC-E2E-06` | 6 | Fresh Upload | Ingest `students.csv` after clear | Clean state established; students table indexed and queryable. | PASS |
