from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import schema
import quality
import llm
import sql_runner
import ingest_handler
import semantic_metadata
import semantic_embeddings
import nl2sql
from auth import get_current_user
from typing import Any, Dict, List, Optional
import os
import shutil
import threading
import json
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="SchemaSense AI API", version="1.0.0")

@app.on_event("startup")
def startup_event():
    """Warmup the Ollama model on FastAPI startup to reduce first-query latency."""
    def warmup():
        try:
            llm.ask_llm("SELECT 1;", task="sql")
        except Exception:
            pass
    threading.Thread(target=warmup, daemon=True).start()

# CORS Configuration for Hackathon (Frontend local + Vercel)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ngrok browser warning bypass middleware (Crucial for Vercel/axios to work)
@app.middleware("http")
async def ngrok_header(request: Request, call_next):
    response = await call_next(request)
    response.headers['ngrok-skip-browser-warning'] = 'true'
    return response

# --- DUMMY ENDPOINTS FOR MEMBER 2 (FRONTEND) & MEMBER 3 (3D VIZ) ---

@app.get("/")
def read_root():
    return {"status": "SchemaSense AI Backend is running"}


@app.get("/health")
def health():
    """Lightweight health endpoint for tunnel/debug checks."""
    return {"status": "ok"}

@app.get("/me")
def read_current_user(user: Dict[str, Any] = Depends(get_current_user)):
    """A test endpoint to verify your frontend JWT configuration."""
    return {"user": user, "message": "Authentication successful!"}

@app.get("/schema")
def get_schema():
    """Returns the actual database schema and relationships built by schema.py"""
    return schema.extract_schema()


@app.get("/relationships")
def get_relationships():
    """Returns formal FK relationships if present; falls back to inferred relationships. Formatted for the 3D Graph frontend."""
    schema_data = schema.extract_schema()
    nodes = schema_data.get("tables", [])
    
    # Map edges to exactly what the graph expects
    rel_data = schema.extract_relationships()
    edges = rel_data.get("relationships", [])
    
    for edge in edges:
        # Frontend logic likes type to be 'explicit' or 'implicit'
        # Since we modified the underlying return dicts previously, ensure strict typing.
        if "type" not in edge or edge.get("type", "") not in ["explicit", "implicit"]:
            edge["type"] = "explicit" if edge.get("inference_method") == "sqlite_foreign_key_list" else "implicit"

    exports = _build_relationship_exports(edges)

    response = {
        "nodes": nodes,
        "edges": edges,
        "relationship_lines": exports["relationship_lines"],
        "mermaid_relationships": exports["mermaid_relationships"],
        "diagnostics": rel_data.get("diagnostics", {})
    }
        
    return response

class ChatRequest(BaseModel):
    query: Optional[str] = None
    mode: Optional[str] = "sql_chat"
    table: Optional[str] = None
    column: Optional[str] = None
    question: Optional[str] = None
    
class ColumnChatRequest(BaseModel):
    table: str
    column: str
    question: str
    
class TableReasoningRequest(BaseModel):
    table_name: str
    columns: Optional[List[Dict[str, Any]]] = None


class GenerateSummaryRequest(BaseModel):
    schema_data: Dict[str, Any]
    user_context: Optional[str] = None

import sqlite3

def get_working_conn():
    return sqlite3.connect("database.sqlite")


def _get_table_names_fast() -> List[str]:
    """Fast table list without triggering full schema inference."""
    conn = get_working_conn()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
    names = [row[0] for row in cur.fetchall()]
    conn.close()
    return names


def _normalize_health_score(value: Any) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, score))


def _normalize_metric_ratio(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        ratio = float(value) / 100.0
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(1.0, ratio)), 4)


def _quality_summary_for_tables(tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary: List[Dict[str, Any]] = []
    for item in tables:
        table_name = item.get("name")
        if not table_name:
            continue

        result = quality.compute_quality(table_name)
        if "error" in result:
            summary.append({
                "table": table_name,
                "health_score": 0,
                "column_count": 0,
                "error": result["error"],
            })
            continue

        summary.append({
            "table": result.get("table", table_name),
            "health_score": _normalize_health_score(result.get("health_score", 0)),
            "completeness": _normalize_metric_ratio(result.get("completeness")),
            "freshness": _normalize_metric_ratio(result.get("freshness")),
            "consistency": _normalize_metric_ratio(result.get("consistency")),
            "column_count": len(result.get("columns", [])),
        })

    return summary


def _generate_natural_answer(
    question: str,
    sql: str,
    columns: List[str],
    rows: List[Dict[str, Any]],
    row_count: int,
) -> str:
    """Generate a non-technical answer grounded in actual SQL output."""
    try:
        prompt = llm.prompt_interpret_results(
            question=question,
            sql=sql,
            columns=columns,
            rows=rows,
            row_count=row_count,
        )
        answer = llm.ask_llm(prompt, task="interpret")
        cleaned = _clean_llm_freeform(answer)
        if cleaned:
            return cleaned
    except Exception:
        pass

    if row_count == 0:
        return "No matching records were found for your question."

    return "The query completed successfully and returned matching records for your request."

@app.post("/chat")
def handle_nl_to_sql(payload: ChatRequest):
    """Enriched NL to SQL powered by local Ollama."""
    try:
        query_text = payload.query or ""
        conn = get_working_conn()
        
        # Build enriched schema with actual sample values but filtered for relevance
        relevant_tables = llm.get_relevant_tables(conn, query_text)
        schema_context = llm.build_schema_context(conn, table_names=relevant_tables)
        
        # Generate SQL with grounded prompt
        sql_prompt = llm.prompt_nl_to_sql(query_text, schema_context)
        sql = llm.ask_llm(sql_prompt, task="sql").strip()
        
        # Clean up any accidental markdown the LLM adds
        sql = llm.extract_sql_clean(sql)
        queried_tables = sql_runner.extract_queried_tables(sql)
        
        # Validate columns
        is_valid, _ = llm.validate_sql_columns(sql, conn)
        if not is_valid:
            sql = llm.safe_sql_fallback(conn)
            queried_tables = sql_runner.extract_queried_tables(sql)
            
        # Execute the SQL
        try:
            # We'll use the safe sql_runner to execute read-only queries with fallback handling
            execution = sql_runner.execute_read_only_sql(sql)
            if not execution["ok"]:
                raise Exception(execution["error"])
                
            results = execution["rows"]
            columns = execution["columns"]
            row_count = execution["row_count"]
            
        except Exception as sql_error:
            # Self-healing loop: let LLM attempt to fix the error once
            try:
                fix_prompt = llm.prompt_fix_sql(sql, str(sql_error), schema_context)
                fixed_sql = llm.ask_llm(fix_prompt, task="fix_sql").strip()
                fixed_sql = llm.extract_sql_clean(fixed_sql)
                
                execution = sql_runner.execute_read_only_sql(fixed_sql)
                if not execution["ok"]:
                    raise Exception(f"Fix failed: {execution['error']} | Original error: {str(sql_error)}")
                    
                sql = fixed_sql  # update to the successfully fixed SQL
                queried_tables = sql_runner.extract_queried_tables(sql)
                results = execution["rows"]
                columns = execution["columns"]
                row_count = execution["row_count"]
                
            except Exception as final_error:
                fallback_sql = llm.safe_sql_fallback(conn)
                fallback_execution = sql_runner.execute_read_only_sql(fallback_sql)
                queried_tables = sql_runner.extract_queried_tables(fallback_sql)
                fallback_natural_answer = _generate_natural_answer(
                    query_text,
                    fallback_sql,
                    fallback_execution["columns"],
                    fallback_execution["rows"],
                    fallback_execution["row_count"],
                )
                return {
                    "sql": fallback_sql,
                    "generated_sql": sql,
                    "explanation": f"SQL execution failed even after self-correction: {str(final_error)}. Returning fallback data.",
                    "natural_answer": fallback_natural_answer,
                    "data": fallback_execution["rows"],
                    "columns": fallback_execution["columns"],
                    "queried_tables": queried_tables,
                    "row_count": fallback_execution["row_count"],
                    "truncated": fallback_execution["truncated"],
                    "execution_ok": False,  # Changed from fallback_execution["ok"] to satisfy contract
                    "execution_error": str(final_error),
                    "used_fallback": True,
                    "reason": "sql_execution_error"
                }
        
        # The grounded result interpretation is the user-facing explanation.
        # Previously this made an extra, overlapping model call before making the
        # interpretation call, adding a full generation to every chat request.
        natural_answer = _generate_natural_answer(query_text, sql, columns, results, row_count)
        explanation = natural_answer
        
        return {
            "sql": sql,
            "explanation": explanation,
            "natural_answer": natural_answer,
            "data": results,
            "columns": columns,
            "queried_tables": queried_tables,
            "row_count": row_count,
            "truncated": execution["truncated"],
            "execution_ok": True,
            "execution_error": None,
            "used_fallback": False,
            "reason": "success"
        }
        
    except Exception as e:
        return {
            "sql": "",
            "explanation": f"Query failed: {str(e)}",
            "natural_answer": "I could not answer that question because the query failed to run.",
            "data": [],
            "columns": [],
            "queried_tables": [],
            "row_count": 0,
            "truncated": False,
            "execution_ok": False,
            "execution_error": str(e),
            "used_fallback": False,
            "reason": "internal_error"
        }

@app.post("/query/stream")
def query_stream(payload: ChatRequest):
    """Streaming endpoint for NL to SQL with Server-Sent Events (SSE)."""
    
    if payload.mode == "column_chat":
        def column_chat_stream():
            import datetime
            start_time = datetime.datetime.now()
            try:
                conn = get_working_conn()
                if not payload.table or not payload.column or not payload.question:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Missing table, column or question'})}\n\n"
                    return
                    
                context = llm.build_column_context(conn, payload.table, payload.column)
                if not context:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Table or column not found'})}\n\n"
                    return
                
                meta_payload = {
                    "row_count": context["row_count"],
                    "data_type": context["data_type"],
                    "null_pct": context["null_pct"] if context["null_pct"] is not None else None,
                    "unique_count": context["unique_count"] if context["unique_count"] is not None else None,
                    "uniqueness_pct": context["uniqueness_pct"] if context["uniqueness_pct"] is not None else None,
                    "top_values": context.get("top_values", []),
                    "sample_values": context.get("sample_values", []),
                    "fk_reference": context.get("fk_reference")
                }
                yield f"data: {json.dumps({'type': 'meta', 'context': meta_payload})}\n\n"
                
                prompt = llm.prompt_column_chat(context, payload.question)
                
                answer = ""
                for chunk in llm.ask_llm_stream(prompt, task="explain"):
                    clean_chunk = chunk
                    control_tokens = ["<|system|>", "<|user|>", "<|assistant|>", "<|end|>"]
                    for token in control_tokens:
                        clean_chunk = clean_chunk.replace(token, "")
                    if clean_chunk:
                        answer += clean_chunk
                        yield f"data: {json.dumps({'type': 'delta', 'chunk': clean_chunk})}\n\n"
                        
                latency_ms = int((datetime.datetime.now() - start_time).total_seconds() * 1000)
                final_payload = {
                    "table": payload.table,
                    "column": payload.column,
                    "question": payload.question,
                    "answer": answer.strip(),
                    "diagnostics": {
                        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "model": llm.MODEL_NAME,
                        "latency_ms": latency_ms
                    }
                }
                yield f"data: {json.dumps({'type': 'done', 'payload': final_payload})}\n\n"
                
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                
        return StreamingResponse(column_chat_stream(), media_type="text/event-stream")

    def event_stream():
        try:
            query_text = payload.query or ""
            conn = get_working_conn()
            relevant_tables = llm.get_relevant_tables(conn, query_text)
            schema_context = llm.build_schema_context(conn, table_names=relevant_tables)
            sql_prompt = llm.prompt_nl_to_sql(query_text, schema_context)
            
            raw_sql = ""
            for chunk in llm.ask_llm_stream(sql_prompt, task="sql"):
                raw_sql += chunk
                yield f"data: {json.dumps({'type': 'sql_chunk', 'chunk': chunk})}\n\n"
            
            sql = llm.extract_sql_clean(raw_sql)
            queried_tables = sql_runner.extract_queried_tables(sql)
            is_valid, _ = llm.validate_sql_columns(sql, conn)
            
            if not is_valid:
                sql = llm.safe_sql_fallback(conn)
                queried_tables = sql_runner.extract_queried_tables(sql)
                
            used_fallback = False
            execution_ok = True
            execution_error = None
            
            execution = sql_runner.execute_read_only_sql(sql)
            if not execution["ok"]:
                try:
                    fix_prompt = llm.prompt_fix_sql(sql, str(execution["error"]), schema_context)
                    fixed_raw_sql = ""
                    for chunk in llm.ask_llm_stream(fix_prompt, task="fix_sql"):
                        fixed_raw_sql += chunk
                        yield f"data: {json.dumps({'type': 'sql_chunk', 'chunk': chunk})}\n\n"
                    sql = llm.extract_sql_clean(fixed_raw_sql)
                    execution = sql_runner.execute_read_only_sql(sql)
                    if not execution["ok"]:
                        raise Exception(execution["error"])
                except Exception as final_error:
                    sql = llm.safe_sql_fallback(conn)
                    execution = sql_runner.execute_read_only_sql(sql)
                    used_fallback = True
                    execution_ok = False
                    execution_error = str(final_error)
            
            queried_tables = sql_runner.extract_queried_tables(sql)
            yield f"data: {json.dumps({'type': 'execution_result', 'data': execution['rows'], 'columns': execution['columns']})}\n\n"
            
            explain_prompt = llm.prompt_explain_sql(sql, query_text, execution["row_count"])
            explanation = ""
            for chunk in llm.ask_llm_stream(explain_prompt, task="explain"):
                explanation += chunk
                yield f"data: {json.dumps({'type': 'explanation_chunk', 'chunk': chunk})}\n\n"
                
            final_payload = {
                "sql": sql,
                "generated_sql": raw_sql,
                "explanation": explanation.strip(),
                "data": execution["rows"],
                "columns": execution["columns"],
                "queried_tables": queried_tables,
                "row_count": execution["row_count"],
                "truncated": execution["truncated"],
                "execution_ok": execution_ok,
                "execution_error": execution_error,
                "used_fallback": used_fallback,
                "reason": "sql_execution_error" if used_fallback else "success"
            }
            yield f"data: {json.dumps({'type': 'done', 'payload': final_payload})}\n\n"
            
        except Exception as e:
            final_payload = {
                "sql": "",
                "generated_sql": "",
                "explanation": f"Query failed: {str(e)}",
                "data": [],
                "columns": [],
                "queried_tables": [],
                "row_count": 0,
                "truncated": False,
                "execution_ok": False,
                "execution_error": str(e),
                "used_fallback": False,
                "reason": "internal_error"
            }
            yield f"data: {json.dumps({'type': 'done', 'payload': final_payload})}\n\n"
            
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.post("/query")
def query_alias(payload: ChatRequest):
    """Compatibility alias for frontend expecting /query."""
    return handle_nl_to_sql(payload)

@app.post("/table-reasoning")
def table_reasoning(payload: TableReasoningRequest):
    """Dedicated non-SQL endpoint for dictionary reasoning."""
    try:
        conn = get_working_conn()
        schema_context = llm.build_schema_context(conn, table_names=[payload.table_name])
        prompt = llm.prompt_table_reasoning(payload.table_name, schema_context)
        explanation = llm.ask_llm(prompt, task="explain").strip()
        
        # Clean control tokens if they leak
        control_tokens = ["<|system|>", "<|user|>", "<|assistant|>", "<|end|>"]
        for token in control_tokens:
            explanation = explanation.replace(token, "")
            
        return {"explanation": explanation.strip()}
    except Exception as e:
        return {"explanation": f"Failed to generate reasoning: {str(e)}"}

@app.post("/column-chat")
def column_chat(payload: ColumnChatRequest):
    """Endpoint for column-level Q&A."""
    import datetime
    start_time = datetime.datetime.now()
    
    if not payload.table or not payload.column or not payload.question:
        raise HTTPException(status_code=400, detail="table, column, and question are required")
        
    try:
        conn = get_working_conn()
        context = llm.build_column_context(conn, payload.table, payload.column)
        if not context:
            raise HTTPException(status_code=404, detail=f"Table '{payload.table}' or column '{payload.column}' not found")
            
        prompt = llm.prompt_column_chat(context, payload.question)
        answer = llm.ask_llm(prompt, task="explain").strip()
        
        # Clean control tokens if they leak
        control_tokens = ["<|system|>", "<|user|>", "<|assistant|>", "<|end|>"]
        for token in control_tokens:
            answer = answer.replace(token, "")
            
        latency_ms = int((datetime.datetime.now() - start_time).total_seconds() * 1000)
            
        return {
            "table": payload.table,
            "column": payload.column,
            "question": payload.question,
            "answer": answer.strip(),
            "context": {
                "row_count": context["row_count"],
                "data_type": context["data_type"],
                "null_pct": context["null_pct"],
                "unique_count": context["unique_count"],
                "uniqueness_pct": context["uniqueness_pct"],
                "top_values": context["top_values"],
                "sample_values": context["sample_values"],
                "fk_reference": context["fk_reference"]
            },
            "diagnostics": {
                "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "model": llm.MODEL_NAME,
                "latency_ms": latency_ms
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}

@app.get("/health/llm")
def llm_health():
    """Health status for local Ollama and configured model availability."""
    return llm.health_check()

@app.get("/quality/{table_name}")
def get_table_quality(table_name: str):
    """Real quality health score data for Heatmap mode using quality.py"""
    result = quality.compute_quality(table_name)
    if "error" in result:
        return {
            "table": table_name,
            "health_score": 0,
            "columns": [],
            "error": result["error"],
        }

    result["health_score"] = _normalize_health_score(result.get("health_score", 0))
    result["completeness"] = _normalize_metric_ratio(result.get("completeness"))
    result["freshness"] = _normalize_metric_ratio(result.get("freshness"))
    result["consistency"] = _normalize_metric_ratio(result.get("consistency"))
    return result


@app.get("/quality")
def get_quality(table: Optional[str] = None):
    """Compatibility endpoint: returns one table quality or all tables summary."""
    if table:
        return get_table_quality(table)

    try:
        table_names = _get_table_names_fast()
        summary = _quality_summary_for_tables([{"name": n} for n in table_names])

        import datetime
        diagnostics = {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "scoring_formula_version": "1.1",
            "tables_scored": len(summary)
        }

        return {
            "mode": "all_tables",
            "table_count": len(summary),
            "items": summary,
            "diagnostics": diagnostics
        }
    except FileNotFoundError:
        return {
            "mode": "all_tables",
            "table_count": 0,
            "items": [],
            "error": "database.sqlite is missing."
        }


@app.post("/graph-data")
def get_graph_data():
    """Returns schema, relationships, and quality in one payload for fast graph bootstrapping."""
    try:
        schema_data = schema.extract_schema()
        relationships_data = schema.extract_relationships()
        
        quality_items = _quality_summary_for_tables(schema_data.get("tables", []))

        return {
            "schema": schema_data,
            "relationships": relationships_data,
            "quality": {
                "mode": "all_tables",
                "table_count": len(quality_items),
                "items": quality_items,
            },
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _build_summary_schema_context(schema_data: Dict[str, Any]) -> str:
    tables = schema_data.get("tables", []) if isinstance(schema_data, dict) else []
    exports = _build_relationship_exports_from_schema_data(schema_data)
    relationship_lines = exports.get("relationship_lines", [])

    table_lines: List[str] = []
    for table in tables[:12]:
        tname = table.get("name") or table.get("id") or "unknown_table"
        row_count = table.get("row_count", table.get("rowCount", "?"))
        columns = table.get("columns", [])
        column_names = []
        if isinstance(columns, list):
            for col in columns[:8]:
                cname = col.get("name") if isinstance(col, dict) else str(col)
                if cname:
                    column_names.append(str(cname))
        table_lines.append(
            f"- {tname}: rows={row_count}, columns={', '.join(column_names) if column_names else 'n/a'}"
        )

    relationship_snippet = relationship_lines[:25] if isinstance(relationship_lines, list) else []
    rel_text = "\n".join([f"- {line}" for line in relationship_snippet]) if relationship_snippet else "- none"

    return (
        f"Table count: {len(tables)}\n"
        f"Tables:\n" + "\n".join(table_lines) + "\n\n"
        f"Relationships:\n{rel_text}"
    )


def _build_relationship_exports(links: List[Dict[str, Any]]) -> Dict[str, Any]:
    relationship_lines: List[str] = []
    mermaid_lines: List[str] = ["graph LR"]
    node_map: Dict[str, str] = {}
    node_index = 0

    for link in links:
        source = link.get("source") or link.get("source_table")
        target = link.get("target") or link.get("target_table")
        source_col = link.get("source_col", "")
        target_col = link.get("target_col", "")

        if not source or not target:
            continue

        relationship_lines.append(f"[{source}] {source_col} -> [{target}] {target_col}")

        if source not in node_map:
            node_map[source] = f"N{node_index}"
            node_index += 1
        if target not in node_map:
            node_map[target] = f"N{node_index}"
            node_index += 1

        label = f"{source_col}->{target_col}" if source_col or target_col else "rel"
        mermaid_lines.append(
            f"  {node_map[source]}[{source}] -->|{label}| {node_map[target]}[{target}]"
        )

    return {
        "relationship_lines": relationship_lines,
        "mermaid_relationships": "\n".join(mermaid_lines),
    }


def _build_relationship_exports_from_schema_data(schema_data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(schema_data, dict):
        return {"relationship_lines": [], "mermaid_relationships": "graph LR"}

    existing_lines = schema_data.get("relationship_lines")
    existing_mermaid = schema_data.get("mermaid_relationships")
    if isinstance(existing_lines, list) and isinstance(existing_mermaid, str) and existing_mermaid.strip():
        return {
            "relationship_lines": existing_lines,
            "mermaid_relationships": existing_mermaid,
        }

    links = schema_data.get("links", [])
    if not isinstance(links, list):
        links = []

    return _build_relationship_exports(links)


def _fallback_report_summary(schema_data: Dict[str, Any], user_context: Optional[str]) -> Dict[str, Any]:
    tables = schema_data.get("tables", []) if isinstance(schema_data, dict) else []
    total_rows = 0
    table_brief: List[str] = []
    for table in tables:
        table_name = table.get("name") or table.get("id") or "unknown_table"
        rows = table.get("row_count", table.get("rowCount", 0))
        try:
            rows_int = int(rows)
            total_rows += rows_int
            table_brief.append(f"{table_name} ({rows_int:,} rows)")
        except (TypeError, ValueError):
            table_brief.append(f"{table_name} (rows n/a)")

    context_text = user_context.strip() if user_context else "general analytics"
    relationship_lines = schema_data.get("relationship_lines", []) if isinstance(schema_data, dict) else []
    if not isinstance(relationship_lines, list):
        relationship_lines = []
    links = schema_data.get("links", []) if isinstance(schema_data, dict) else []
    if not isinstance(links, list):
        links = []
    relationship_count = len(relationship_lines) if relationship_lines else len(links)
    top_tables = ", ".join(table_brief[:4]) if table_brief else "no table details provided"

    return {
        "executive_summary": (
            f"This dataset spans {len(tables)} tables with approximately {total_rows:,} rows, giving enough analytical depth to support {context_text}. "
            f"The primary structure is anchored by {top_tables}, which indicates a transactional core with supporting dimensions suitable for KPI, cohort, and funnel diagnostics. "
            f"From a strategic viewpoint, the presence of {relationship_count} detected inter-table links suggests the data can support cross-entity analysis rather than isolated table reporting. "
            f"The strongest opportunity is to combine entity-level joins with quality scoring to identify high-impact drivers behind performance shifts and customer outcomes. "
            f"A non-obvious risk is silent join inflation or deflation if relationship assumptions are used without validating key uniqueness and orphan behavior across tables. "
            f"For leadership reporting, this dataset is mature enough for executive dashboards, but should be paired with data-contract checks to keep trend narratives trustworthy over time. "
            f"For delivery teams, the next milestone should be a governed semantic layer that standardizes business metrics before scaling self-serve analytics."
        ),
        "key_findings": [
            f"Detected {len(tables)} tables and about {total_rows:,} rows for downstream analysis.",
            f"Identified {relationship_count} relationship mappings suitable for 2D ER presentation.",
            "Schema is rich enough for both operational reporting and predictive feature engineering.",
            "Cross-table quality governance is required to avoid misleading joins in executive dashboards.",
        ],
        "statistical_insights": (
            "Available profiling and quality signals indicate the dataset can be assessed along completeness, freshness, and consistency dimensions. "
            "This supports confidence-weighted analytics where tables with weaker quality can be down-weighted in decision workflows. "
            "Relationship topology further enables linked variance analysis, helping teams attribute movement in downstream KPIs to upstream data behavior."
        ),
        "recommendations": [
            "Establish table-level quality SLOs and alerting thresholds before scaling executive dashboards.",
            "Validate key cardinality and orphan ratios for every critical relationship in the ER map.",
            "Build a reusable metric layer so business definitions stay stable across teams.",
            "Prioritize enrichment of high-value entities first, then expand to long-tail tables.",
        ],
    }


def _clean_llm_freeform(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    for token in ["```json", "```", "<|system|>", "<|user|>", "<|assistant|>", "<|end|>"]:
        cleaned = cleaned.replace(token, "")
    return " ".join(cleaned.split())


@app.post("/api/generate-summary")
def generate_summary(payload: GenerateSummaryRequest):
    schema_context = _build_summary_schema_context(payload.schema_data)
    prompt = llm.prompt_generate_summary_json(schema_context, payload.user_context)
    exports = _build_relationship_exports_from_schema_data(payload.schema_data)
    raw_response = ""

    try:
        raw_response = llm.ask_llm(prompt, task="executive_summary")
        parsed = llm.extract_json_object(raw_response)
    except Exception:
        parsed = None

    if not isinstance(parsed, dict):
        fallback = _fallback_report_summary(payload.schema_data, payload.user_context)
        fallback["relationship_lines"] = exports["relationship_lines"]
        fallback["mermaid_relationships"] = exports["mermaid_relationships"]
        return fallback

    executive_summary = parsed.get("executive_summary")
    key_findings = parsed.get("key_findings")
    statistical_insights = parsed.get("statistical_insights")
    recommendations = parsed.get("recommendations")

    if not isinstance(executive_summary, str):
        executive_summary = ""
    if not isinstance(statistical_insights, str):
        statistical_insights = ""
    if not isinstance(key_findings, list):
        key_findings = []
    if not isinstance(recommendations, list):
        recommendations = []

    key_findings_clean = [str(item) for item in key_findings if isinstance(item, (str, int, float))]
    recommendations_clean = [str(item) for item in recommendations if isinstance(item, (str, int, float))]

    if not executive_summary or not statistical_insights:
        fallback = _fallback_report_summary(payload.schema_data, payload.user_context)
        executive_summary = executive_summary or fallback["executive_summary"]
        statistical_insights = statistical_insights or fallback["statistical_insights"]
        if not key_findings_clean:
            key_findings_clean = fallback["key_findings"]
        if not recommendations_clean:
            recommendations_clean = fallback["recommendations"]

    return {
        "executive_summary": executive_summary,
        "key_findings": key_findings_clean,
        "statistical_insights": statistical_insights,
        "recommendations": recommendations_clean,
        "relationship_lines": exports["relationship_lines"],
        "mermaid_relationships": exports["mermaid_relationships"],
    }


@app.post("/ingest/clear")
def clear_database():
    """Explicitly wipe the database and semantic layer for a new upload session."""
    if os.path.exists("database.sqlite"):
        try:
            os.remove("database.sqlite")
        except Exception:
            pass
            
    # Invalidate and wipe semantic metadata & FAISS index
    try:
        semantic_embeddings.clear_semantic_state()
    except Exception as e:
        logger.warning(f"Failed to clear semantic artifacts: {e}")

    return {"status": "cleared", "message": "Database and semantic layer wiped for new session."}

@app.post("/ingest/file")
async def ingest_file(file: UploadFile = File(...), clear: bool = False):
    """Upload endpoint for CSV/SQLite files; loads user data into database.sqlite
    Use ?clear=true query param to wipe the DB before the first file in a session.
    """
    if clear:
        if os.path.exists("database.sqlite"):
            try:
                os.remove("database.sqlite")
            except Exception:
                pass
        try:
            semantic_embeddings.clear_semantic_state()
        except Exception:
            pass
            
    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)

    saved_path = os.path.join(upload_dir, file.filename)
    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    ext = os.path.splitext(file.filename)[1].lower()
    
    # Process based on file type
    if ext == ".csv":
        # CSV: Parse and load into database.sqlite
        result = ingest_handler.create_table_from_csv(saved_path)
        semantic_sync = _sync_semantic_layer_after_ingest(result.get("success", False))
        return {
            "status": "uploaded",
            "file_type": "CSV",
            "filename": file.filename,
            "saved_path": saved_path,
            **result,  # Includes success, table_name, row_count, error, etc.
            "semantic_sync": semantic_sync,
            "next": f"Call GET /schema to verify table '{result['table_name']}' is now active." if result['success'] else "CSV parsing failed; check error message."
        }
    
    elif ext in {".sqlite", ".db"}:
        # SQLite: Copy directly to database.sqlite
        result = ingest_handler.copy_sqlite_database(saved_path)
        semantic_sync = _sync_semantic_layer_after_ingest(result.get("success", False))
        return {
            "status": "uploaded",
            "file_type": "SQLite",
            "filename": file.filename,
            "saved_path": saved_path,
            **result,  # Includes success, table_count, tables, error
            "semantic_sync": semantic_sync,
            "next": f"Call GET /schema to verify {result['table_count']} tables are now active." if result['success'] else "Database copy failed; check error message."
        }
        
    elif ext == ".zip":
        # ZIP: Extract and load all CSVs
        result = ingest_handler.process_zip_file(saved_path)
        semantic_sync = _sync_semantic_layer_after_ingest(result.get("success", False))
        return {
            "status": "uploaded",
            "file_type": "ZIP",
            "filename": file.filename,
            "saved_path": saved_path,
            **result,  # Includes success, table_count, tables, error
            "semantic_sync": semantic_sync,
            "next": f"Call GET /schema to verify {result.get('table_count', 0)} tables are now active." if result.get('success') else "ZIP processing failed."
        }
    
    else:
        return {
            "status": "error",
            "filename": file.filename,
            "error": f"Unsupported file type: {ext}. Only .csv, .zip, .sqlite, and .db are supported.",
            "next": "Please upload a CSV, ZIP containing CSVs, or SQLite database file."
        }


def _sync_semantic_layer_after_ingest(ingest_success: bool) -> Dict[str, Any]:
    """Helper to safely synchronize metadata_store.json and FAISS index after database modification."""
    if not ingest_success or not os.path.exists("database.sqlite"):
        return {"status": "skipped", "reason": "Ingest did not succeed or database does not exist."}
    return semantic_embeddings.sync_semantic_state(db_path="database.sqlite", use_llm=False)


def _fmt_num(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_int(value: Any) -> str:
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return "0"


def _deterministic_table_analysis(table_name: str, data: Dict[str, Any]) -> str:
    numeric = data.get("numeric_stats") or []
    categorical = data.get("categorical_stats") or []
    date_stats = data.get("date_stats") or []
    correlations = data.get("correlation_pairs") or []

    lines: List[str] = []

    lines.append("### Distribution Analysis")
    if numeric:
        for row in numeric[:3]:
            col = row.get("column", "unknown")
            lines.append(
                f"- `{col}` mean={_fmt_num(row.get('mean'))}, median={_fmt_num(row.get('median'))}, std={_fmt_num(row.get('std'))}, range=[{_fmt_num(row.get('min'))}, {_fmt_num(row.get('max'))}]"
            )
    else:
        lines.append("- Insufficient evidence from available profile (no numeric columns detected).")

    lines.append("### Outlier Report")
    if numeric:
        for row in numeric[:3]:
            col = row.get("column", "unknown")
            iqr_out = _fmt_int(row.get("iqr_outlier_count") or 0)
            z_out = _fmt_int(row.get("zscore_outlier_count") or 0)
            lines.append(f"- `{col}` outliers: IQR={iqr_out}, Z-score(>3)={z_out}")
    else:
        lines.append("- Insufficient evidence from available profile (outlier metrics unavailable).")

    lines.append("### Categorical Entropy")
    if categorical:
        for row in categorical[:3]:
            col = row.get("column", "unknown")
            lines.append(
                f"- `{col}` cardinality={_fmt_int(row.get('cardinality'))}, entropy={_fmt_num(row.get('entropy'))}"
            )
    else:
        lines.append("- Insufficient evidence from available profile (no categorical columns detected).")

    lines.append("### Temporal Patterns")
    if date_stats:
        for row in date_stats[:3]:
            col = row.get("column", "unknown")
            lines.append(
                f"- `{col}` window={row.get('min_date', 'n/a')} to {row.get('max_date', 'n/a')}, range_days={row.get('date_range_days', 'n/a')}, peak={row.get('most_active_period', 'n/a')}"
            )
    else:
        lines.append("- Insufficient evidence from available profile (no temporal columns detected).")

    lines.append("### Correlation Insights")
    if correlations:
        for pair in correlations[:3]:
            left = pair.get("col_a", "unknown_a")
            right = pair.get("col_b", "unknown_b")
            lines.append(f"- `{left}` vs `{right}` has Pearson r={_fmt_num(pair.get('r'), 3)}")
    else:
        lines.append("- Insufficient evidence from available profile (correlation pairs unavailable).")

    lines.append("### Modeling Readiness")
    lines.append(
        f"- `{table_name}` is suitable for baseline analytics pipelines if null handling and outlier strategy are codified before production scoring."
    )
    lines.append(
        "- Recommended controls: schema contracts, column-level null policy, and feature drift checks on top numeric and categorical drivers."
    )

    return "\n".join(lines)


@app.get("/analysis/{table_name}")
def get_table_analysis(table_name: str, include_llm: bool = True):
    import time
    from datetime import datetime, timezone
    start_time = time.time()
    
    from analysis import compute_analysis
    from new_llm_funcs import prompt_table_analysis
    import llm
    
    try:
        data = compute_analysis(table_name)
    except Exception as e:
        return {"error": str(e)}

    analysis_text = ""
    llm_used = False

    if include_llm:
        prompt = prompt_table_analysis(
            table_name,
            data["numeric_stats"],
            data["categorical_stats"],
            data["date_stats"],
            data["correlation_pairs"]
        )
        try:
            analysis_text = llm.ask_llm(prompt, task="summary")
            llm_used = bool((analysis_text or "").strip())
        except Exception:
            analysis_text = ""

    if not (analysis_text or "").strip():
        analysis_text = _deterministic_table_analysis(table_name, data)

    data["analysis_text"] = analysis_text
    
    end_time = time.time()
    data["diagnostics"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "formula_version": "1.0.0",
        "latency_ms": int((end_time - start_time) * 1000),
        "llm_requested": include_llm,
        "llm_used": llm_used,
    }
    
    return data


class SemanticGenerateRequest(BaseModel):
    use_llm: Optional[bool] = True


@app.post("/semantic/generate")
def generate_semantic_metadata(payload: Optional[SemanticGenerateRequest] = None):
    """Explicitly generate/regenerate structured semantic metadata and FAISS index for active database."""
    try:
        use_llm = payload.use_llm if payload is not None and payload.use_llm is not None else True
        result = semantic_metadata.generate_all_metadata(use_llm=use_llm)
        
        # Rebuild FAISS index from the newly written metadata
        index_status = {}
        try:
            index_status = semantic_embeddings.rebuild_index()
        except Exception as idx_err:
            index_status = {"status": "warning", "error": f"Index rebuild failed: {str(idx_err)}"}

        return {
            "status": "success",
            "message": f"Semantic metadata generated successfully for {result.get('table_count', 0)} tables.",
            "version": result.get("version"),
            "generated_at": result.get("generated_at"),
            "table_count": result.get("table_count", 0),
            "tables": list(result.get("tables", {}).keys()),
            "index": index_status,
            "diagnostics": result.get("diagnostics", {}),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Semantic metadata generation failed: {str(e)}")


@app.get("/semantic/status")
def get_semantic_metadata_status():
    """Report semantic metadata state, staleness, database fingerprint, and FAISS index status."""
    try:
        status = semantic_metadata.get_semantic_status()
        status["index"] = semantic_embeddings.get_index_status()
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get semantic status: {str(e)}")


class NL2SQLGenerateRequest(BaseModel):
    question: str
    top_k: Optional[int] = 8


@app.post("/nl2sql/generate")
def generate_nl2sql(payload: NL2SQLGenerateRequest):
    """Context-aware NL-to-SQL generation endpoint.
    Retrieves semantic schema via FAISS, reconstructs context, and queries Qwen3.5:4b.
    NOTE: Generates SQL only; does NOT execute the SQL statement.
    """
    if not payload.question or not str(payload.question).strip():
        raise HTTPException(status_code=400, detail="Question field cannot be empty.")
    try:
        top_k = payload.top_k or 8
        result = nl2sql.generate_sql(payload.question, top_k=top_k)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"NL-to-SQL generation failed: {str(e)}")


class NL2SQLQueryRequest(BaseModel):
    question: str
    max_retries: Optional[int] = 2
    top_k: Optional[int] = 8


@app.post("/nl2sql/query")
def query_nl2sql(payload: NL2SQLQueryRequest):
    """Context-aware NL-to-SQL execution endpoint with SQLGlot validation and bounded self-correction.
    Retrieves schema -> Generates candidate -> Validates AST -> Self-corrects if invalid -> Executes on SQLite -> Returns results + explanation.
    """
    if not payload.question or not str(payload.question).strip():
        raise HTTPException(status_code=400, detail="Question field cannot be empty.")
    try:
        top_k = payload.top_k or 8
        max_retries = payload.max_retries if payload.max_retries is not None else 2
        result = nl2sql.query(payload.question, max_retries=max_retries, top_k=top_k)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"NL-to-SQL query pipeline failed: {str(e)}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
