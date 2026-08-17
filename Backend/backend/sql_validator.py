"""
SQLGlot SQL Validation and Safety Layer for SchemaSense AI.

Parses and validates LLM-generated SQLite queries against the active database schema
using SQLGlot AST inspection to guarantee:
1. Syntactically valid SQLite dialect syntax.
2. Read-only safety (only SELECT / WITH CTE queries).
3. Prohibition of data mutation, schema changes, PRAGMAs, and administrative commands.
4. Single-statement enforcement.
5. Grounding against active SQLite tables and columns.
NOTE: This module validates SQL only; it NEVER executes SQL.
"""

import os
import sqlite3
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, SqlglotError

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "database.sqlite"

# Explicitly forbidden statement types in SQLGlot AST
FORBIDDEN_EXPRESSION_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Pragma,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Merge,
)


def get_active_db_schema(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Set[str]]:
    """
    Queries the active SQLite database directly to extract authoritative table and column names.
    Returns: { "table_name_lower": {"col1_lower", "col2_lower", ...} }
    """
    if not os.path.exists(db_path):
        return {}

    schema_map: Dict[str, Set[str]] = {}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [row[0] for row in cur.fetchall()]

        for tname in tables:
            cur.execute(f'PRAGMA table_info("{tname}");')
            cols = {row[1].lower() for row in cur.fetchall()}
            schema_map[tname] = cols

        conn.close()
    except Exception as e:
        logger.error(f"Failed to read schema from database '{db_path}': {e}")

    return schema_map


def _extract_cte_and_table_aliases(statement: exp.Expression) -> Tuple[Set[str], Dict[str, str]]:
    """
    Extracts CTE definitions and table alias mappings from the SQLGlot AST.
    Returns:
      cte_names: set of CTE names defined in WITH clauses (e.g. {'user_counts'})
      alias_to_table: dict mapping lowercase alias to lowercase real table (e.g. {'s': 'survey', 'a': 'answer'})
    """
    cte_names: Set[str] = set()
    alias_to_table: Dict[str, str] = {}

    # 1. Identify CTE names in WITH clauses
    for cte in statement.find_all(exp.CTE):
        name = cte.alias_or_name
        if name:
            cte_names.add(name.lower())

    # 2. Identify Table aliases
    for table_expr in statement.find_all(exp.Table):
        raw_name = table_expr.name.lower()
        alias = table_expr.alias.lower() if table_expr.alias else None
        if alias:
            alias_to_table[alias] = raw_name
        # The table itself maps to itself
        alias_to_table[raw_name] = raw_name

    return cte_names, alias_to_table


def _extract_select_column_aliases(statement: exp.Expression) -> Set[str]:
    """Extracts column alias names defined in the SELECT list (e.g., 'SELECT COUNT(*) AS answer_count')."""
    aliases: Set[str] = set()
    for select_expr in statement.find_all(exp.Select):
        for expr in select_expr.expressions:
            if isinstance(expr, exp.Alias) and expr.alias:
                aliases.add(expr.alias.lower())
    return aliases


def validate_sql(
    sql: str,
    db_path: str = DEFAULT_DB_PATH,
    active_schema: Optional[Dict[str, Set[str]]] = None,
) -> Dict[str, Any]:
    """
    Performs comprehensive AST-based validation of an SQLite query.
    Returns structured validation report indicating validity, syntax status, read-only status,
    detected tables/columns, errors, and warnings.
    """
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    clean_sql = (sql or "").strip()
    if not clean_sql:
        return {
            "valid": False,
            "syntax_valid": False,
            "read_only": False,
            "dialect": "sqlite",
            "tables": [],
            "columns": [],
            "errors": [{"code": "EMPTY_SQL_ERROR", "message": "SQL query cannot be empty."}],
            "warnings": [],
        }

    # 1. SQLGlot Parse
    try:
        parsed_statements = sqlglot.parse(clean_sql, read="sqlite")
    except (ParseError, SqlglotError, Exception) as parse_err:
        return {
            "valid": False,
            "syntax_valid": False,
            "read_only": False,
            "dialect": "sqlite",
            "tables": [],
            "columns": [],
            "errors": [{
                "code": "SQL_PARSE_ERROR",
                "message": f"Syntax error parsing SQLite query: {str(parse_err)}"
            }],
            "warnings": [],
        }

    if not parsed_statements:
        return {
            "valid": False,
            "syntax_valid": False,
            "read_only": False,
            "dialect": "sqlite",
            "tables": [],
            "columns": [],
            "errors": [{"code": "EMPTY_STATEMENT_ERROR", "message": "No valid SQL statement found."}],
            "warnings": [],
        }

    # 2. Multiple Statements Check
    if len(parsed_statements) > 1:
        return {
            "valid": False,
            "syntax_valid": False,
            "read_only": False,
            "dialect": "sqlite",
            "tables": [],
            "columns": [],
            "errors": [{
                "code": "MULTIPLE_STATEMENTS_ERROR",
                "message": f"Multiple SQL statements detected ({len(parsed_statements)}). Only single-statement read-only queries are permitted."
            }],
            "warnings": [],
        }

    statement = parsed_statements[0]
    if statement is None:
        return {
            "valid": False,
            "syntax_valid": False,
            "read_only": False,
            "dialect": "sqlite",
            "tables": [],
            "columns": [],
            "errors": [{"code": "NULL_STATEMENT_ERROR", "message": "Statement parsed as null expression."}],
            "warnings": [],
        }

    # 3. Read-Only AST Validation
    # Check top-level statement is a Select or Union or contains Select
    is_select_type = isinstance(statement, (exp.Select, exp.Union))
    if not is_select_type:
        errors.append({
            "code": "NON_SELECT_STATEMENT_ERROR",
            "message": f"Statement must be a read-only SELECT query, got '{statement.key.upper()}'."
        })

    # Check for forbidden expressions anywhere in the AST
    for forbidden_type in FORBIDDEN_EXPRESSION_TYPES:
        for node in statement.find_all(forbidden_type):
            errors.append({
                "code": f"FORBIDDEN_OPERATION_{node.key.upper()}",
                "message": f"Forbidden state-modifying operation '{node.key.upper()}' detected in query."
            })

    # Explicit string check for ATTACH, DETACH, VACUUM, PRAGMA keywords as defense-in-depth
    upper_sql = clean_sql.upper()
    for forbidden_kw in ("ATTACH", "DETACH", "VACUUM", "PRAGMA", "DROP TABLE", "ALTER TABLE", "TRUNCATE"):
        if forbidden_kw in upper_sql:
            # If not already caught by AST
            if not any(forbidden_kw in e["message"] for e in errors):
                errors.append({
                    "code": f"FORBIDDEN_KEYWORD_{forbidden_kw.replace(' ', '_')}",
                    "message": f"Forbidden keyword '{forbidden_kw}' detected in query."
                })

    # 4. Extract Tables & Validate against SQLite Schema
    if active_schema is None:
        active_schema = get_active_db_schema(db_path)

    # Normalize active_schema map:
    # schema_lookup: lower_table_name -> (original_table_name, {lower_col_names})
    schema_lookup: Dict[str, Tuple[str, Set[str]]] = {}
    if active_schema:
        for orig_t, cols in active_schema.items():
            schema_lookup[orig_t.lower()] = (orig_t, {c.lower() for c in cols})

    cte_names, alias_to_table = _extract_cte_and_table_aliases(statement)
    referenced_tables: List[str] = []
    found_tables_set: Set[str] = set()

    for table_expr in statement.find_all(exp.Table):
        raw_tname = table_expr.name
        if not raw_tname:
            continue
        lowered_t = raw_tname.lower()

        # Skip CTE references
        if lowered_t in cte_names:
            continue

        if lowered_t not in found_tables_set:
            found_tables_set.add(lowered_t)
            # Find the true casing in active schema if available
            real_name = schema_lookup[lowered_t][0] if lowered_t in schema_lookup else raw_tname
            referenced_tables.append(real_name)

        # Validate existence in active database schema
        if schema_lookup and lowered_t not in schema_lookup:
            errors.append({
                "code": "UNKNOWN_TABLE_ERROR",
                "message": f"Table '{raw_tname}' does not exist in the active database schema."
            })

    # 5. Extract Columns & Validate against Schema
    select_aliases = _extract_select_column_aliases(statement)
    referenced_columns: List[str] = []
    found_cols_set: Set[str] = set()

    for col_expr in statement.find_all(exp.Column):
        col_name = col_expr.name
        table_qualifier = col_expr.table
        if not col_name:
            continue

        col_lower = col_name.lower()
        full_col_id = f"{table_qualifier}.{col_name}" if table_qualifier else col_name
        if full_col_id.lower() not in found_cols_set:
            found_cols_set.add(full_col_id.lower())
            referenced_columns.append(full_col_id)

        # Skip column alias references used in GROUP BY / ORDER BY / HAVING
        if not table_qualifier and col_lower in select_aliases:
            continue

        if schema_lookup:
            if table_qualifier:
                # Resolve alias or table name
                resolved_table = alias_to_table.get(table_qualifier.lower(), table_qualifier.lower())
                # If resolved table is a CTE, skip physical schema check
                if resolved_table in cte_names:
                    continue

                table_entry = schema_lookup.get(resolved_table)
                if table_entry is not None and col_lower not in table_entry[1]:
                    errors.append({
                        "code": "UNKNOWN_COLUMN_ERROR",
                        "message": f"Column '{col_name}' does not exist in table '{table_qualifier}'."
                    })
            else:
                # Unqualified column: must exist in at least one of the referenced physical tables or CTEs
                if found_tables_set:
                    exists_in_any = False
                    for t in found_tables_set:
                        if t in schema_lookup and col_lower in schema_lookup[t][1]:
                            exists_in_any = True
                            break
                    if not exists_in_any and not any(cte in cte_names for cte in alias_to_table):
                        errors.append({
                            "code": "UNKNOWN_COLUMN_ERROR",
                            "message": f"Column '{col_name}' does not exist in any of the referenced tables ({', '.join(referenced_tables)})."
                        })

    # Deduplicate errors
    unique_errors: List[Dict[str, str]] = []
    seen_error_keys = set()
    for err in errors:
        k = (err["code"], err["message"])
        if k not in seen_error_keys:
            seen_error_keys.add(k)
            unique_errors.append(err)

    is_valid = len(unique_errors) == 0
    read_only_status = not any("FORBIDDEN" in e["code"] or "NON_SELECT" in e["code"] for e in unique_errors)

    return {
        "valid": is_valid,
        "syntax_valid": True,
        "read_only": read_only_status,
        "dialect": "sqlite",
        "tables": referenced_tables,
        "columns": referenced_columns,
        "errors": unique_errors,
        "warnings": warnings,
    }
