"""
Semantic Metadata Generation Layer for SchemaSense AI.

Extracts observed facts directly from SQLite schema, quality profiling,
and statistical analysis, then enriches them with grounded semantic
descriptions, aliases, and business roles using Qwen3.5:4b via Ollama.
"""

import os
import json
import time
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import schema
import quality
import analysis
import llm

DB_PATH = "database.sqlite"
METADATA_PATH = "metadata_store.json"
SCHEMA_VERSION = "1.0.0"


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _safe_sample_value(val: Any) -> Any:
    """Sanitizes sample values for safe metadata storage without leaking huge blobs or credentials."""
    if val is None:
        return None
    if isinstance(val, (int, float, bool)):
        return val
    s = str(val).strip()
    if len(s) > 120:
        return s[:117] + "..."
    return s


def get_database_fingerprint(db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Calculates a fingerprint for the SQLite database to track changes and staleness."""
    if not os.path.exists(db_path):
        return None
    try:
        stat = os.stat(db_path)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
        tables = [row[0] for row in cur.fetchall()]
        conn.close()

        return {
            "mtime": stat.st_mtime,
            "size_bytes": stat.st_size,
            "table_count": len(tables),
            "tables": tables,
        }
    except Exception:
        return None


def get_metadata_age(metadata_path: str = METADATA_PATH) -> Optional[float]:
    """Returns the age of metadata_store.json in seconds, or None if file does not exist."""
    if not os.path.exists(metadata_path):
        return None
    try:
        data = load_metadata(metadata_path)
        if data and "generated_at" in data:
            gen_time = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
            return max(0.0, (datetime.now(timezone.utc) - gen_time).total_seconds())
        return max(0.0, time.time() - os.path.getmtime(metadata_path))
    except Exception:
        return None


def is_metadata_stale(metadata_path: str = METADATA_PATH, db_path: str = DB_PATH) -> bool:
    """Checks whether the metadata store is missing or out of sync with the database."""
    if not os.path.exists(metadata_path) or not os.path.exists(db_path):
        return True
    
    metadata = load_metadata(metadata_path)
    if not metadata or not isinstance(metadata, dict):
        return True
    
    stored_fp = metadata.get("database_fingerprint")
    current_fp = get_database_fingerprint(db_path)
    
    if not stored_fp or not current_fp:
        return True
    
    if stored_fp.get("mtime") != current_fp.get("mtime") or \
       stored_fp.get("size_bytes") != current_fp.get("size_bytes") or \
       stored_fp.get("tables") != current_fp.get("tables"):
        return True
        
    return False


def load_metadata(metadata_path: str = METADATA_PATH) -> Optional[Dict[str, Any]]:
    """Reads and parses metadata_store.json from disk."""
    if not os.path.exists(metadata_path):
        return None
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def collect_table_evidence(
    table_name: str,
    schema_data: Optional[Dict[str, Any]] = None,
    rel_data: Optional[Dict[str, Any]] = None,
    db_path: str = DB_PATH,
) -> Dict[str, Any]:
    """
    Collects observed facts (schema, column stats, sample values, relationships, quality, profiling)
    for a specific table directly from SQLite without LLM hallucination.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file '{db_path}' does not exist.")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. Direct row count from target db_path
    try:
        cur.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table_name)}")
        row_count = int(cur.fetchone()[0])
    except Exception:
        row_count = 0

    # 2. Schema info from provided schema_data or PRAGMA inspection
    raw_columns = []
    if schema_data is not None:
        table_schema = next(
            (t for t in schema_data.get("tables", []) if t.get("name") == table_name or t.get("id") == table_name),
            None
        )
        if table_schema:
            raw_columns = table_schema.get("columns", [])
    
    if not raw_columns:
        cur.execute(f"PRAGMA table_info({_quote_identifier(table_name)});")
        pragma_cols = cur.fetchall()
        cur.execute(f"PRAGMA foreign_key_list({_quote_identifier(table_name)});")
        pragma_fks = cur.fetchall()
        fk_set = {fk[3] for fk in pragma_fks}
        fk_map = {fk[3]: f"{fk[2]}.{fk[4] or 'id'}" for fk in pragma_fks}

        for pcol in pragma_cols:
            cname = pcol[1]
            raw_columns.append({
                "name": cname,
                "type": pcol[2] or "TEXT",
                "is_pk": bool(pcol[5] > 0),
                "is_fk": cname in fk_set,
                "nullable": pcol[3] == 0,
                "references": fk_map.get(cname),
            })

    # 3. Relationships involving this table
    table_rels = []
    if rel_data is not None:
        all_rels = rel_data.get("relationships", [])
        table_rels = [
            r for r in all_rels
            if r.get("source_table") == table_name or r.get("target_table") == table_name or
               r.get("source") == table_name or r.get("target") == table_name
        ]
    else:
        # Check formal FKs from pragma
        cur.execute(f"PRAGMA foreign_key_list({_quote_identifier(table_name)});")
        for fk in cur.fetchall():
            table_rels.append({
                "source_table": table_name,
                "source_col": fk[3],
                "target_table": fk[2],
                "target_col": fk[4] or "id",
                "type": "formal",
                "confidence": 1.0,
            })

    # 3. Quality metrics
    try:
        quality_metrics = quality.compute_quality(table_name)
        if "error" in quality_metrics:
            quality_metrics = {"health_score": 0, "completeness": 0, "freshness": None, "consistency": 100, "orphan_issues": []}
    except Exception:
        quality_metrics = {"health_score": 0, "completeness": 0, "freshness": None, "consistency": 100, "orphan_issues": []}

    # 4. Statistical analysis
    try:
        analysis_data = analysis.compute_analysis(table_name)
    except Exception:
        analysis_data = {
            "numeric_stats": [],
            "categorical_stats": [],
            "date_stats": [],
            "correlation_pairs": []
        }

    # 5. Build rich column evidence with safe bounded samples
    columns_observed: Dict[str, Dict[str, Any]] = {}
    
    for col in raw_columns:
        cname = col.get("name")
        if not cname:
            continue
        
        col_type = col.get("type", "TEXT")
        is_pk = bool(col.get("is_pk") or col.get("is_primary_key"))
        is_fk = bool(col.get("is_fk") or col.get("foreign_key"))
        nullable = bool(col.get("nullable", True))
        null_pct = float(col.get("null_percentage", col.get("null_percent", 0.0) or 0.0))
        uniqueness = float(col.get("uniqueness", col.get("uniqueness_percent", 0.0) or 0.0))
        fk_ref = col.get("references")

        # Fetch sample values & top distribution safely
        sample_vals: List[Any] = []
        top_vals: List[Dict[str, Any]] = []
        unique_count: Optional[int] = None

        if row_count > 0:
            try:
                col_ctx = llm.build_column_context(conn, table_name, cname)
                if col_ctx:
                    sample_vals = [_safe_sample_value(v) for v in col_ctx.get("sample_values", [])[:5]]
                    top_vals = [
                        {"value": _safe_sample_value(item.get("value")), "count": item.get("count")}
                        for item in col_ctx.get("top_values", [])[:5]
                    ]
                    unique_count = col_ctx.get("unique_count")
                    if col_ctx.get("null_pct") is not None:
                        null_pct = float(col_ctx.get("null_pct"))
                    if col_ctx.get("uniqueness_pct") is not None:
                        uniqueness = float(col_ctx.get("uniqueness_pct"))
                    if col_ctx.get("fk_reference") and not fk_ref:
                        fk_ref = col_ctx.get("fk_reference")
            except Exception:
                sample_vals = [_safe_sample_value(col.get("sample"))] if col.get("sample") is not None else []
        else:
            sample_vals = []

        columns_observed[cname] = {
            "name": cname,
            "type": col_type,
            "nullable": nullable,
            "is_pk": is_pk,
            "is_fk": is_fk,
            "null_percentage": null_pct,
            "uniqueness": uniqueness,
            "unique_count": unique_count,
            "sample_values": [v for v in sample_vals if v is not None],
            "top_values": top_vals,
            "fk_reference": fk_ref,
        }

    conn.close()

    return {
        "table_name": table_name,
        "row_count": row_count,
        "column_count": len(columns_observed),
        "columns": columns_observed,
        "relationships": table_rels,
        "quality": {
            "health_score": quality_metrics.get("health_score", 0),
            "completeness": quality_metrics.get("completeness"),
            "freshness": quality_metrics.get("freshness"),
            "freshness_latest_date": quality_metrics.get("freshness_latest_date"),
            "consistency": quality_metrics.get("consistency"),
            "orphan_issues": quality_metrics.get("orphan_issues", []),
        },
        "statistics": {
            "numeric_stats": analysis_data.get("numeric_stats", []),
            "categorical_stats": analysis_data.get("categorical_stats", []),
            "date_stats": analysis_data.get("date_stats", []),
            "correlation_pairs": analysis_data.get("correlation_pairs", []),
        },
    }


def _infer_column_business_role(col_meta: Dict[str, Any]) -> str:
    """Deterministic inference of business role based on column characteristics."""
    name_lower = col_meta.get("name", "").lower()
    col_type = (col_meta.get("type") or "TEXT").upper()
    is_pk = col_meta.get("is_pk", False)
    is_fk = col_meta.get("is_fk", False)
    
    if is_pk:
        return "primary_key"
    if is_fk or name_lower.endswith("_id") or name_lower.endswith("id"):
        return "foreign_key" if is_fk else "identifier"
    if any(kw in name_lower for kw in ["date", "time", "created", "updated", "_at", "_on", "timestamp"]) or "TIME" in col_type or "DATE" in col_type:
        return "timestamp"
    if any(kw in name_lower for kw in ["status", "state", "type", "category", "flag", "mode", "gender"]):
        return "status" if "status" in name_lower or "state" in name_lower else "dimension"
    if any(kw in name_lower for kw in ["amount", "price", "total", "count", "score", "rate", "cost", "salary", "qty", "quantity"]) or col_type in ("INTEGER", "FLOAT", "REAL", "NUMERIC"):
        return "measure"
    if any(kw in name_lower for kw in ["name", "title", "label", "city", "country", "region", "description", "text", "body"]):
        return "text_content" if "text" in name_lower or "body" in name_lower or "desc" in name_lower else "dimension"
    
    return "attribute"


def _deterministic_fallback_metadata(table_name: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Generates grounded fallback metadata when Ollama/LLM is unavailable."""
    cols = evidence.get("columns", {})
    row_count = evidence.get("row_count", 0)
    col_count = len(cols)
    
    pk_cols = [c for c, m in cols.items() if m.get("is_pk")]
    fk_cols = [c for c, m in cols.items() if m.get("is_fk")]

    display_name = table_name.replace("_", " ").replace("-", " ").strip()
    
    pk_desc = f"keyed by {', '.join(pk_cols)}" if pk_cols else "without explicit primary key"
    fk_desc = f"with foreign links via {', '.join(fk_cols)}" if fk_cols else ""
    desc = f"{table_name} contains {row_count:,} records across {col_count} columns ({pk_desc} {fk_desc}).".strip()

    # Simple domain inference from table name
    t_lower = table_name.lower()
    if any(w in t_lower for w in ["order", "cart", "item", "product", "sku", "payment", "invoice"]):
        domain = "e-commerce"
    elif any(w in t_lower for w in ["survey", "question", "answer", "poll", "response"]):
        domain = "surveys"
    elif any(w in t_lower for w in ["user", "customer", "client", "account", "member", "auth"]):
        domain = "user_management"
    elif any(w in t_lower for w in ["log", "event", "metric", "audit", "trace"]):
        domain = "telemetry"
    elif any(w in t_lower for w in ["patient", "clinical", "medical", "hospital", "doctor"]):
        domain = "healthcare"
    elif any(w in t_lower for w in ["transaction", "bank", "credit", "ledger", "balance"]):
        domain = "finance"
    else:
        domain = "general_analytics"

    # Aliases
    aliases = list(dict.fromkeys([
        display_name,
        table_name.lower(),
        table_name.rstrip("s") if table_name.endswith("s") else table_name + "s"
    ]))

    # Column descriptions
    generated_columns: Dict[str, Dict[str, Any]] = {}
    for cname, cmeta in cols.items():
        role = _infer_column_business_role(cmeta)
        samples = cmeta.get("sample_values", [])
        sample_str = f" (e.g. {', '.join(str(s) for s in samples[:3])})" if samples else ""
        
        c_desc = f"{cname} stores {cmeta.get('type', 'TEXT')} data representing the {cname.replace('_', ' ')}{sample_str}."
        c_aliases = [cname.replace("_", " "), cname.lower()]
        
        generated_columns[cname] = {
            "description": c_desc,
            "semantic_aliases": list(dict.fromkeys(c_aliases)),
            "business_role": role,
        }

    common_questions = [
        f"How many records are in {table_name}?",
        f"What is the distribution of {list(cols.keys())[0]} in {table_name}?" if cols else f"Show sample data from {table_name}",
    ]
    if pk_cols:
        common_questions.append(f"Find details for a specific {pk_cols[0]} in {table_name}")

    return {
        "table_description": desc,
        "business_domain": domain,
        "semantic_aliases": aliases,
        "columns": generated_columns,
        "common_questions": common_questions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "deterministic_fallback",
        "source": "fallback",
    }


def prompt_table_semantic_metadata(table_name: str, evidence: Dict[str, Any]) -> str:
    """Builds an evidence-grounded prompt for Qwen3.5:4b."""
    row_count = evidence.get("row_count", 0)
    cols = evidence.get("columns", {})
    rels = evidence.get("relationships", [])
    quality_info = evidence.get("quality", {})
    stats = evidence.get("statistics", {})

    col_lines = []
    for cname, cdata in cols.items():
        pk_tag = " [PRIMARY KEY]" if cdata.get("is_pk") else ""
        fk_tag = f" [FOREIGN KEY -> {cdata.get('fk_reference')}]" if cdata.get("is_fk") or cdata.get("fk_reference") else ""
        samples = ", ".join(repr(v) for v in cdata.get("sample_values", [])[:3])
        sample_part = f"; sample values: [{samples}]" if samples else ""
        col_lines.append(f"- {cname} ({cdata.get('type', 'TEXT')}{pk_tag}{fk_tag}, null={cdata.get('null_percentage', 0.0)}%, unique={cdata.get('uniqueness', 0.0)}%{sample_part})")

    rel_lines = []
    for r in rels:
        rel_lines.append(f"- {r.get('source_table')}.{r.get('source_col')} -> {r.get('target_table')}.{r.get('target_col')} ({r.get('type', 'relationship')})")

    cols_str = "\n".join(col_lines) if col_lines else "- No columns found"
    rels_str = "\n".join(rel_lines) if rel_lines else "- No relationships detected"

    num_stats = stats.get("numeric_stats", [])
    numeric_summary = ", ".join(f"{s.get('column')}: mean={s.get('mean')}, range=[{s.get('min')}, {s.get('max')}]" for s in num_stats[:3]) if num_stats else "None"

    return f"""<|system|>
You are an expert data architect and database ontology engineer. Your task is to generate precise, grounded semantic metadata for a single database table.

CRITICAL INSTRUCTIONS:
1. Base all descriptions, business roles, semantic aliases, and questions strictly on the provided evidence.
2. Do NOT invent columns, tables, relationships, or statistics.
3. Keep descriptions factual, concise, and non-generic.
4. Output MUST be valid JSON only. Do not include markdown code fences, reasoning tokens, or conversational preface.

REQUIRED JSON FORMAT:
{{
  "table_description": "2-3 concise sentences explaining the purpose and content of the table.",
  "business_domain": "Short domain identifier (e.g. 'e-commerce', 'surveys', 'finance', 'healthcare', 'operations')",
  "semantic_aliases": ["alias 1", "alias 2"],
  "columns": {{
    "<column_name>": {{
      "description": "1 concise sentence explaining what this column stores and its analytical role.",
      "semantic_aliases": ["synonym 1", "synonym 2"],
      "business_role": "one of: primary_key, foreign_key, identifier, measure, dimension, status, timestamp, text_content, attribute"
    }}
  }},
  "common_questions": [
    "Useful business question 1?",
    "Useful business question 2?",
    "Useful business question 3?"
  ]
}}<|end|>
<|user|>
TABLE NAME: {table_name}
TOTAL ROWS: {row_count:,}

COLUMNS & SAMPLES:
{cols_str}

RELATIONSHIPS:
{rels_str}

DATA QUALITY HEALTH SCORE: {quality_info.get('health_score', 'n/a')}/100
NUMERIC METRICS SUMMARY: {numeric_summary}

Generate the semantic metadata JSON for `{table_name}` now:<|end|>
<|assistant|>"""


def generate_table_metadata(table_name: str, evidence: Dict[str, Any], use_llm: bool = True) -> Dict[str, Any]:
    """
    Generates semantic metadata for a table using Qwen3.5:4b via Ollama,
    falling back gracefully to deterministic analysis if LLM fails or is disabled.
    """
    if not use_llm:
        return _deterministic_fallback_metadata(table_name, evidence)

    try:
        prompt = prompt_table_semantic_metadata(table_name, evidence)
        raw_response = llm.ask_llm(prompt, task="summary")
        parsed = llm.extract_json_object(raw_response)

        if not parsed or not isinstance(parsed, dict):
            return _deterministic_fallback_metadata(table_name, evidence)

        # Validate and sanitize LLM response
        table_desc = parsed.get("table_description")
        if not isinstance(table_desc, str) or not table_desc.strip():
            fallback = _deterministic_fallback_metadata(table_name, evidence)
            table_desc = fallback["table_description"]

        domain = parsed.get("business_domain")
        if not isinstance(domain, str) or not domain.strip():
            domain = "general_analytics"

        aliases = parsed.get("semantic_aliases")
        if not isinstance(aliases, list):
            aliases = [table_name.replace("_", " "), table_name.lower()]
        else:
            aliases = [str(a).strip() for a in aliases if str(a).strip()]

        # Columns
        raw_col_meta = parsed.get("columns", {})
        col_evidence = evidence.get("columns", {})
        sanitized_columns: Dict[str, Dict[str, Any]] = {}

        for cname, cdata in col_evidence.items():
            llm_col = raw_col_meta.get(cname, {}) if isinstance(raw_col_meta, dict) else {}
            
            c_desc = llm_col.get("description") if isinstance(llm_col, dict) else None
            if not isinstance(c_desc, str) or not c_desc.strip():
                role = _infer_column_business_role(cdata)
                c_desc = f"{cname} stores {cdata.get('type', 'TEXT')} values for {cname.replace('_', ' ')}."
            else:
                c_desc = c_desc.strip()

            c_aliases = llm_col.get("semantic_aliases") if isinstance(llm_col, dict) else []
            if not isinstance(c_aliases, list):
                c_aliases = [cname.replace("_", " ")]
            else:
                c_aliases = [str(a).strip() for a in c_aliases if str(a).strip()]
            if cname.replace("_", " ") not in c_aliases:
                c_aliases.append(cname.replace("_", " "))

            c_role = llm_col.get("business_role") if isinstance(llm_col, dict) else None
            valid_roles = {"primary_key", "foreign_key", "identifier", "measure", "dimension", "status", "timestamp", "text_content", "attribute"}
            if not c_role or c_role not in valid_roles:
                c_role = _infer_column_business_role(cdata)

            sanitized_columns[cname] = {
                "description": c_desc,
                "semantic_aliases": list(dict.fromkeys(c_aliases)),
                "business_role": c_role,
            }

        questions = parsed.get("common_questions")
        if not isinstance(questions, list):
            questions = [f"What records are in {table_name}?"]
        else:
            questions = [str(q).strip() for q in questions if str(q).strip()]

        return {
            "table_description": table_desc,
            "business_domain": domain,
            "semantic_aliases": list(dict.fromkeys(aliases)),
            "columns": sanitized_columns,
            "common_questions": questions,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": llm.MODEL_NAME,
            "source": "llm",
        }

    except Exception:
        return _deterministic_fallback_metadata(table_name, evidence)


def generate_all_metadata(
    db_path: str = DB_PATH,
    metadata_path: str = METADATA_PATH,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """
    Orchestrates full metadata generation for the active database.
    Separates observed facts from LLM-generated semantic interpretations,
    and performs atomic file writing to prevent corrupt store files.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file '{db_path}' not found. Please upload or ingest data first.")

    start_time = time.time()
    fingerprint = get_database_fingerprint(db_path)
    if not fingerprint or not fingerprint.get("tables"):
        raise ValueError(f"No tables found in database '{db_path}'.")

    # Extract global schema & relationships once
    schema_data = schema.extract_schema()
    rel_data = schema.extract_relationships()

    tables_metadata: Dict[str, Dict[str, Any]] = {}
    generation_errors: Dict[str, str] = {}

    for table_name in fingerprint["tables"]:
        try:
            evidence = collect_table_evidence(
                table_name=table_name,
                schema_data=schema_data,
                rel_data=rel_data,
                db_path=db_path,
            )
            generated = generate_table_metadata(
                table_name=table_name,
                evidence=evidence,
                use_llm=use_llm,
            )

            tables_metadata[table_name] = {
                "observed": evidence,
                "generated": generated,
            }
        except Exception as e:
            generation_errors[table_name] = str(e)
            # If one table fails, produce deterministic fallback for it rather than destroying everything
            try:
                evidence = collect_table_evidence(table_name, schema_data, rel_data, db_path)
                fallback_generated = _deterministic_fallback_metadata(table_name, evidence)
                tables_metadata[table_name] = {
                    "observed": evidence,
                    "generated": fallback_generated,
                }
            except Exception as e2:
                # Fatal table failure
                raise RuntimeError(f"Failed to generate metadata for table '{table_name}': {str(e2)}") from e2

    metadata_document = {
        "version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "semantic_metadata.py",
        "model": llm.MODEL_NAME if use_llm else "deterministic_fallback",
        "database_file": os.path.basename(db_path),
        "database_fingerprint": fingerprint,
        "table_count": len(tables_metadata),
        "tables": tables_metadata,
        "diagnostics": {
            "duration_seconds": round(time.time() - start_time, 2),
            "use_llm": use_llm,
            "errors": generation_errors,
        }
    }

    # Atomic Write: write to .tmp then rename
    tmp_path = metadata_path + f".tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(metadata_document, f, indent=2, ensure_ascii=False)
        
        # Atomic replacement
        os.replace(tmp_path, metadata_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise IOError(f"Failed to atomically write metadata file '{metadata_path}': {str(e)}") from e

    return metadata_document


def get_semantic_status(metadata_path: str = METADATA_PATH, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Returns the current state and diagnostics of semantic metadata."""
    metadata_exists = os.path.exists(metadata_path)
    metadata = load_metadata(metadata_path) if metadata_exists else None
    
    current_fp = get_database_fingerprint(db_path)
    stale = is_metadata_stale(metadata_path, db_path)
    age_sec = get_metadata_age(metadata_path)

    tables_info = []
    if metadata and "tables" in metadata:
        for tname, tdata in metadata["tables"].items():
            obs = tdata.get("observed", {})
            gen = tdata.get("generated", {})
            tables_info.append({
                "table_name": tname,
                "row_count": obs.get("row_count", 0),
                "column_count": obs.get("column_count", 0),
                "business_domain": gen.get("business_domain"),
                "source": gen.get("source", "unknown"),
            })

    return {
        "metadata_exists": metadata_exists,
        "version": metadata.get("version") if metadata else None,
        "generated_at": metadata.get("generated_at") if metadata else None,
        "model": metadata.get("model") if metadata else None,
        "age_seconds": round(age_sec, 1) if age_sec is not None else None,
        "is_stale": stale,
        "table_count": metadata.get("table_count", 0) if metadata else 0,
        "database_fingerprint": current_fp,
        "tables": tables_info,
    }
