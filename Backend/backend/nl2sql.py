"""
Context-Aware NL-to-SQL Generation Layer for SchemaSense AI.

Translates natural language database queries into SQLite SQL by:
1. Retrieving semantically relevant schema metadata using FAISS (all-MiniLM-L6-v2).
2. Performing 1-hop relationship expansion for join inference.
3. Constructing bounded, grounded SQLite prompt context.
4. Generating SQL via Qwen3.5:4b (Ollama).
5. Extracting and returning structured SQL candidates without executing them.
"""

import os
import json
import time
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import llm
import semantic_metadata
import semantic_embeddings

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 8


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
            c_aliases = cgen.get("semantic_aliases", [])
            
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


def parse_sql_response(raw_response: str) -> str:
    """
    Extracts and sanitizes the SQL statement from the model's response.
    Prefers structured JSON parsing with robust regex and fallback extraction.
    """
    if not raw_response or not raw_response.strip():
        return ""

    # 1. Try structured JSON parsing
    parsed_json = llm.extract_json_object(raw_response)
    if parsed_json and isinstance(parsed_json, dict) and "sql" in parsed_json:
        candidate_sql = str(parsed_json["sql"]).strip()
        cleaned = llm.extract_sql_clean(candidate_sql)
        if cleaned:
            return cleaned

    # 2. Fallback to extracting SQL from raw text
    cleaned_fallback = llm.extract_sql_clean(raw_response)
    if cleaned_fallback:
        return cleaned_fallback

    return raw_response.strip()


def generate_sql(
    question: str,
    top_k: int = DEFAULT_TOP_K,
    metadata_path: str = semantic_metadata.METADATA_PATH,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """
    End-to-end context-aware NL-to-SQL generator:
    question -> FAISS retrieval -> context reconstruction -> prompt -> Qwen3.5:4b -> SQL.
    NOTE: Does NOT execute the generated SQL.
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

    latency_ms = int((time.time() - start_time) * 1000)

    return {
        "status": "success",
        "question": clean_question,
        "sql": sql_candidate,
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
