"""
Context-Aware NL-to-SQL Generation, Validation, and Bounded Self-Correction Pipeline.

Provides:
1. FAISS-retrieved semantic schema context reconstruction (all-MiniLM-L6-v2 + IndexFlatIP).
2. Grounded SQLite SQL generation via Qwen3.5:4b.
3. Strict AST-based SQLGlot validation before database execution.
4. Bounded self-correction loop (MAX_RETRIES = 2) for validation and runtime errors.
5. Safe read-only SQLite execution with result serialization.
6. Grounded natural-language interpretation of executed results.
"""

import os
import re
import json
import time
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import llm
import sql_runner
import semantic_metadata
import semantic_embeddings
import sql_validator

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 8
MAX_RETRIES = 2


def build_sql_context(
    retrieved_items: List[Dict[str, Any]],
    metadata_path: str = semantic_metadata.METADATA_PATH,
    expand_relationships: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    """
    Reconstructs a compact, highly relevant schema context from retrieved FAISS items
    and performs 1-hop relationship expansion to support accurate JOINs.
    """
    metadata = semantic_metadata.load_metadata(metadata_path) or {}
    tables_meta = metadata.get("tables", {})

    if not retrieved_items or not tables_meta:
        return "No relevant schema found in metadata.", {"tables": [], "columns": [], "relationships": [], "expanded_tables": []}

    # 1. Identify directly retrieved tables and columns
    direct_tables: Set[str] = set()
    retrieved_columns: Dict[str, Set[str]] = {}

    for item in retrieved_items:
        tname = item.get("table")
        cname = item.get("column")
        if tname and tname in tables_meta:
            direct_tables.add(tname)
            if tname not in retrieved_columns:
                retrieved_columns[tname] = set()
            if cname:
                retrieved_columns[tname].add(cname)

    # 2. 1-hop Relationship Expansion
    expanded_tables: Set[str] = set()
    active_relationships: List[Dict[str, Any]] = []

    for tname in list(direct_tables):
        t_data = tables_meta.get(tname, {})
        rels = t_data.get("observed", {}).get("relationships", [])
        
        for r in rels:
            src_t = r.get("source_table") or r.get("source")
            tgt_t = r.get("target_table") or r.get("target")
            src_c = r.get("source_col")
            tgt_c = r.get("target_col")
            
            if src_t and tgt_t:
                active_relationships.append({
                    "source_table": src_t,
                    "source_col": src_c,
                    "target_table": tgt_t,
                    "target_col": tgt_c,
                    "type": r.get("type", "foreign_key"),
                })
                if expand_relationships:
                    # Include the foreign table in context if it's connected
                    neighbor = tgt_t if src_t == tname else src_t
                    if neighbor in tables_meta and neighbor not in direct_tables:
                        expanded_tables.add(neighbor)

    all_context_tables = sorted(list(direct_tables.union(expanded_tables)))

    # Deduplicate relationships
    unique_rels = []
    seen_rel_signatures = set()
    for r in active_relationships:
        sig = (r["source_table"], r["source_col"], r["target_table"], r["target_col"])
        if sig not in seen_rel_signatures:
            seen_rel_signatures.add(sig)
            unique_rels.append(r)

    # 3. Format compact context block
    context_lines: List[str] = []
    context_lines.append("DATABASE DIALECT: SQLite")
    context_lines.append("AVAILABLE TABLES & COLUMNS:")

    for tname in all_context_tables:
        t_data = tables_meta.get(tname, {})
        obs = t_data.get("observed", {})
        gen = t_data.get("generated", {})

        row_count = obs.get("row_count", 0)
        desc = gen.get("table_description", "")
        aliases = gen.get("semantic_aliases", [])
        aliases_str = f" [Aliases: {', '.join(aliases)}]" if aliases else ""

        context_lines.append(f"\nTable: `{tname}` ({row_count:,} rows){aliases_str}")
        if desc:
            context_lines.append(f"  Description: {desc}")
        context_lines.append("  Columns:")

        cols_obs = obs.get("columns", {})
        cols_gen = gen.get("columns", {})

        for cname, cobs in cols_obs.items():
            ctype = cobs.get("type", "TEXT")
            is_pk = " PRIMARY KEY" if cobs.get("is_pk") else ""
            is_fk = " FOREIGN KEY" if cobs.get("is_fk") else ""
            fk_ref = f" REFERENCES {cobs.get('fk_reference')}" if cobs.get("fk_reference") else ""
            
            cgen = cols_gen.get(cname, {})
            c_desc = cgen.get("description", "")
            c_role = cgen.get("business_role", "")
            
            role_tag = f", role: {c_role}" if c_role else ""
            desc_tag = f" — {c_desc}" if c_desc else ""
            
            samples = cobs.get("sample_values", [])
            sample_str = ""
            if samples:
                sample_preview = ", ".join(repr(v) for v in samples[:3])
                sample_str = f" [examples: {sample_preview}]"

            context_lines.append(f"    - `{cname}` {ctype}{is_pk}{is_fk}{fk_ref}{role_tag}{sample_str}{desc_tag}")

    if unique_rels:
        context_lines.append("\nRELATIONSHIPS (JOIN PATHS):")
        for r in unique_rels:
            context_lines.append(f"  - `{r['source_table']}.{r['source_col']}` = `{r['target_table']}.{r['target_col']}`")

    context_str = "\n".join(context_lines)

    summary = {
        "tables": all_context_tables,
        "direct_tables": sorted(list(direct_tables)),
        "expanded_tables": sorted(list(expanded_tables)),
        "columns": [f"{t}.{c}" for t, cols in retrieved_columns.items() for c in cols],
        "relationships": [f"{r['source_table']}.{r['source_col']} -> {r['target_table']}.{r['target_col']}" for r in unique_rels],
    }

    return context_str, summary


def build_sql_prompt(question: str, context_text: str) -> str:
    """
    Constructs an evidence-grounded prompt for Qwen3.5:4b to generate SQLite SQL.
    """
    return f"""<|system|>
You are a principal database engineer and SQLite Text-to-SQL specialist.
Your task is to write a single, correct, read-only SQLite SQL query that directly answers the user's question based STRICTLY on the supplied SCHEMA CONTEXT.

CRITICAL INSTRUCTIONS:
1. Output MUST be valid SQLite syntax only.
2. Use ONLY table and column names that exist in the SCHEMA CONTEXT.
3. Do NOT invent tables, columns, or relationships.
4. Only generate read-only SELECT queries (CTEs using WITH are permitted).
5. For aggregations or groupings, use appropriate GROUP BY, ORDER BY, and LIMIT clauses.
6. When joining tables, strictly use the join conditions specified in the RELATIONSHIPS section.
7. Return your response as a valid JSON object with the following exact keys:
{{
  "sql": "SELECT ...;",
  "reasoning": "Brief 1-sentence explanation of query logic."
}}
8. Do NOT include markdown code blocks, reasoning traces, or conversational text outside the JSON object.<|end|>
<|user|>
SCHEMA CONTEXT:
{context_text}

USER QUESTION:
{question}

Generate the JSON response containing the SQLite SQL query now:<|end|>
<|assistant|>"""


def build_correction_prompt(
    question: str,
    failed_sql: str,
    error_msg: str,
    context_text: str
) -> str:
    """
    Constructs a targeted self-correction prompt for Qwen3.5:4b when validation or execution fails.
    """
    return f"""<|system|>
You are an expert SQLite SQL repair specialist.
Your previous SQL query failed validation or execution against SQLite.
Your task is to fix the query to correctly answer the user question based strictly on the SCHEMA CONTEXT.

CRITICAL RULES:
1. Output MUST be valid SQLite syntax only.
2. Use ONLY table and column names present in the SCHEMA CONTEXT below.
3. Do NOT invent tables, columns, or relationships.
4. Generate read-only queries only (SELECT or CTEs using WITH).
5. Never generate DDL or DML (INSERT, UPDATE, DELETE, DROP, ALTER, PRAGMA, etc.).
6. Return your corrected query as a valid JSON object with the exact keys:
{{
  "sql": "SELECT ...;",
  "reasoning": "Brief explanation of how the error was corrected."
}}
7. Do NOT include markdown code fences or conversational text outside the JSON object.<|end|>
<|user|>
SCHEMA CONTEXT:
{context_text}

ORIGINAL QUESTION:
{question}

PREVIOUS FAILED SQL:
{failed_sql}

ERROR DETAILS:
{error_msg}

Please generate the corrected JSON response containing the valid SQLite query now:<|end|>
<|assistant|>"""


def parse_sql_response(raw_response: str) -> str:
    """
    Extracts and sanitizes the SQL statement from the model's response.
    Prefers structured JSON parsing without silently stripping multi-statements.
    """
    if not raw_response or not raw_response.strip():
        return ""

    # 1. Try structured JSON parsing
    parsed_json = llm.extract_json_object(raw_response)
    if parsed_json and isinstance(parsed_json, dict) and "sql" in parsed_json:
        candidate_sql = str(parsed_json["sql"]).strip()
        # Strip enclosing markdown code block if present
        candidate_sql = re.sub(r"^```(?:sql)?\s*", "", candidate_sql, flags=re.IGNORECASE)
        candidate_sql = re.sub(r"\s*```$", "", candidate_sql)
        return candidate_sql.strip()

    # 2. Fallback to extracting SQL from raw text
    cleaned_fallback = llm.extract_sql_clean(raw_response)
    if cleaned_fallback:
        return cleaned_fallback

    return raw_response.strip()


def execute_validated_sql(
    sql: str,
    db_path: str = sql_validator.DEFAULT_DB_PATH,
    max_rows: int = 200
) -> Dict[str, Any]:
    """
    Executes an SQL query against SQLite ONLY after SQLGlot validation confirms it is valid and read-only.
    Reuses existing safe execution logic from sql_runner.
    """
    start_time = time.time()
    
    # Mandatory Pre-Execution Validation Check
    validation_report = sql_validator.validate_sql(sql, db_path=db_path)
    if not validation_report.get("valid"):
        err_msg = "; ".join(e["message"] for e in validation_report.get("errors", []))
        return {
            "success": False,
            "rows": [],
            "columns": [],
            "row_count": 0,
            "truncated": False,
            "execution_time_ms": int((time.time() - start_time) * 1000),
            "error": f"Pre-execution validation failed: {err_msg}",
        }

    # Safe Read-Only Execution via sql_runner
    exec_result = sql_runner.execute_read_only_sql(sql, max_rows=max_rows)
    exec_time_ms = int((time.time() - start_time) * 1000)

    return {
        "success": bool(exec_result.get("ok")),
        "rows": exec_result.get("rows", []),
        "columns": exec_result.get("columns", []),
        "row_count": exec_result.get("row_count", 0),
        "truncated": exec_result.get("truncated", False),
        "execution_time_ms": exec_time_ms,
        "error": exec_result.get("error"),
    }


def generate_sql(
    question: str,
    top_k: int = DEFAULT_TOP_K,
    metadata_path: str = semantic_metadata.METADATA_PATH,
    db_path: str = sql_validator.DEFAULT_DB_PATH,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """
    End-to-end context-aware NL-to-SQL candidate generator without execution.
    """
    if not question or not str(question).strip():
        raise ValueError("Question cannot be empty.")

    start_time = time.time()
    clean_question = str(question).strip()

    # 1. Semantic Retrieval via FAISS
    retrieved_items = semantic_embeddings.retrieve(
        query_text=clean_question,
        top_k=top_k,
        metadata_path=metadata_path,
        db_path=db_path,
    )

    # 2. Reconstruct schema context with 1-hop relationship expansion
    context_text, context_summary = build_sql_context(
        retrieved_items=retrieved_items,
        metadata_path=metadata_path,
        expand_relationships=True,
    )

    # 3. Build grounded prompt
    prompt = build_sql_prompt(clean_question, context_text)

    # 4. Invoke LLM
    if use_llm:
        try:
            raw_response = llm.ask_llm(prompt, task="sql")
        except Exception as e:
            raise RuntimeError(f"LLM generation failed: {str(e)}") from e
    else:
        # Mock/deterministic fallback for testing without live LLM
        first_table = context_summary["tables"][0] if context_summary.get("tables") else "sqlite_master"
        raw_response = json.dumps({
            "sql": f"SELECT COUNT(*) FROM {first_table};",
            "reasoning": f"Count records in {first_table}"
        })

    # 5. Parse and sanitize SQL
    sql_candidate = parse_sql_response(raw_response)

    # 6. Validate candidate SQL via SQLGlot AST against active schema
    meta = semantic_metadata.load_metadata(metadata_path)
    active_schema = None
    if meta and "tables" in meta and meta["tables"]:
        active_schema = {
            t: set(t_data.get("observed", {}).get("columns", {}).keys())
            for t, t_data in meta["tables"].items()
        }

    validation_report = sql_validator.validate_sql(
        sql_candidate,
        db_path=db_path,
        active_schema=active_schema
    )

    latency_ms = int((time.time() - start_time) * 1000)

    return {
        "status": "success" if validation_report.get("valid") else "invalid_candidate",
        "question": clean_question,
        "sql": sql_candidate,
        "validation": validation_report,
        "model": llm.MODEL_NAME if use_llm else "mock_generator",
        "retrieval": {
            "top_k": top_k,
            "items_count": len(retrieved_items),
            "items": [
                {
                    "type": item.get("type"),
                    "table": item.get("table"),
                    "column": item.get("column"),
                    "score": item.get("score"),
                }
                for item in retrieved_items
            ],
        },
        "context": context_summary,
        "latency_ms": latency_ms,
    }


def query(
    question: str,
    max_retries: int = MAX_RETRIES,
    top_k: int = DEFAULT_TOP_K,
    metadata_path: str = semantic_metadata.METADATA_PATH,
    db_path: str = sql_validator.DEFAULT_DB_PATH,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """
    End-to-end validated NL-to-SQL execution pipeline with bounded self-correction.
    Flow:
      Question -> FAISS Retrieval -> Context Reconstruction ->
      Loop (Attempt 0 .. max_retries):
         Qwen (Generate/Repair) -> Parse -> SQLGlot Validate ->
         If Invalid -> Next Attempt (Self-Correction)
         If Valid -> Safe SQLite Execute ->
            If Runtime Error -> Next Attempt (Self-Correction)
            If Success -> Generate Natural Language Explanation -> Return
    """
    if not question or not str(question).strip():
        raise ValueError("Question cannot be empty.")

    start_time = time.time()
    clean_question = str(question).strip()
    
    # Bounded retries: ensure max_retries is between 0 and 5
    bounded_retries = max(0, min(int(max_retries), 5))

    # 1. Semantic Retrieval via FAISS
    retrieved_items = semantic_embeddings.retrieve(
        query_text=clean_question,
        top_k=top_k,
        metadata_path=metadata_path,
        db_path=db_path,
    )

    # 2. Reconstruct schema context with 1-hop relationship expansion
    context_text, context_summary = build_sql_context(
        retrieved_items=retrieved_items,
        metadata_path=metadata_path,
        expand_relationships=True,
    )

    meta = semantic_metadata.load_metadata(metadata_path)
    active_schema = None
    if meta and "tables" in meta and meta["tables"]:
        active_schema = {
            t: set(t_data.get("observed", {}).get("columns", {}).keys())
            for t, t_data in meta["tables"].items()
        }

    attempts: List[Dict[str, Any]] = []
    last_error: str = ""
    failed_sql: str = ""
    candidate_sql: str = ""

    for attempt_idx in range(bounded_retries + 1):
        if attempt_idx == 0:
            prompt = build_sql_prompt(clean_question, context_text)
            task_type = "sql"
        else:
            prompt = build_correction_prompt(clean_question, failed_sql, last_error, context_text)
            task_type = "fix_sql"

        # Call LLM
        if use_llm:
            try:
                raw_response = llm.ask_llm(prompt, task=task_type)
            except Exception as e:
                raw_response = ""
                last_error = f"LLM generation failed: {str(e)}"
        else:
            first_table = context_summary["tables"][0] if context_summary.get("tables") else "sqlite_master"
            raw_response = json.dumps({
                "sql": f"SELECT COUNT(*) FROM {first_table};",
                "reasoning": f"Count records in {first_table}"
            })

        candidate_sql = parse_sql_response(raw_response)

        # Pre-Execution SQLGlot Validation
        validation_report = sql_validator.validate_sql(
            candidate_sql,
            db_path=db_path,
            active_schema=active_schema
        )

        attempt_record: Dict[str, Any] = {
            "attempt": attempt_idx,
            "sql": candidate_sql,
            "validation": validation_report,
            "execution": None,
        }

        if not validation_report.get("valid"):
            # Validation failure: collect errors and proceed to correction loop
            err_msgs = [e.get("message", "Validation error") for e in validation_report.get("errors", [])]
            last_error = "; ".join(err_msgs) if err_msgs else "Query failed SQLGlot validation."
            failed_sql = candidate_sql
            attempts.append(attempt_record)
            continue

        # Validation Passed -> Execute on SQLite
        exec_result = execute_validated_sql(candidate_sql, db_path=db_path)
        attempt_record["execution"] = exec_result
        attempts.append(attempt_record)

        if exec_result.get("success"):
            # Successful Execution -> Generate Natural-Language Explanation
            rows = exec_result.get("rows", [])
            cols = exec_result.get("columns", [])
            row_cnt = exec_result.get("row_count", 0)

            explanation = ""
            if use_llm:
                try:
                    interpret_prompt = llm.prompt_interpret_results(
                        question=clean_question,
                        sql=candidate_sql,
                        columns=cols,
                        rows=rows,
                        row_count=row_cnt,
                    )
                    explanation = llm.ask_llm(interpret_prompt, task="interpret")
                except Exception:
                    explanation = f"Query executed successfully and returned {row_cnt} record(s)."
            else:
                explanation = f"Query executed successfully and returned {row_cnt} record(s)."

            total_latency_ms = int((time.time() - start_time) * 1000)

            return {
                "status": "success",
                "question": clean_question,
                "sql": candidate_sql,
                "results": rows,
                "columns": cols,
                "row_count": row_cnt,
                "truncated": exec_result.get("truncated", False),
                "explanation": explanation.strip() if explanation else f"Found {row_cnt} matching record(s).",
                "retrieval": {
                    "top_k": top_k,
                    "items": [
                        {
                            "type": item.get("type"),
                            "table": item.get("table"),
                            "column": item.get("column"),
                            "score": item.get("score"),
                        }
                        for item in retrieved_items
                    ],
                },
                "context": context_summary,
                "validation": validation_report,
                "execution": exec_result,
                "attempts": attempts,
                "retry_count": attempt_idx,
                "total_latency_ms": total_latency_ms,
            }
        else:
            # Execution failure: collect SQLite error and proceed to correction loop
            last_error = f"SQLite runtime error: {exec_result.get('error')}"
            failed_sql = candidate_sql

    # If all attempts exhausted without success:
    total_latency_ms = int((time.time() - start_time) * 1000)
    return {
        "status": "failed",
        "question": clean_question,
        "sql": candidate_sql or failed_sql,
        "results": [],
        "columns": [],
        "row_count": 0,
        "explanation": None,
        "error": last_error or "Maximum retry attempts exceeded without producing valid executable SQL.",
        "retrieval": {
            "top_k": top_k,
            "items": [
                {
                    "type": item.get("type"),
                    "table": item.get("table"),
                    "column": item.get("column"),
                    "score": item.get("score"),
                }
                for item in retrieved_items
            ],
        },
        "context": context_summary,
        "attempts": attempts,
        "retry_count": len(attempts) - 1,
        "total_latency_ms": total_latency_ms,
    }
