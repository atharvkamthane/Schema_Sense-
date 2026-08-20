"""
Test Suite for Cross-Dataset Independence & Schema Isolation in SchemaSense AI.

Validates that SchemaSense is genuinely dataset-independent across 3 completely distinct schemas:
- Dataset A: ENJOYSPORT (Single-table meteorological/activity dataset)
- Dataset B: Customers & Orders (Multi-table e-commerce relational schema)
- Dataset C: Employees & Departments (Multi-table enterprise HR relational schema)

Verifies:
1. End-to-end pipeline: Ingest -> Metadata -> FAISS -> Retrieval -> Qwen -> SQLGlot -> Execution -> Explanation
2. Strict schema isolation: Zero cross-dataset entity leakage (e.g. no survey entities in A/B/C, no customers in C, etc.)
3. Sequential in-place dataset replacement on the same database path.
4. Bounded self-correction loop when initial candidate fails validation/execution.
5. Rejection of malicious DDL/DML and SQL injection candidates.
"""

import os
import re
import json
import time
import sqlite3
import pandas as pd
from typing import Any, Dict, List, Optional

import schema
import quality
import analysis
import semantic_metadata
import semantic_embeddings
import sql_validator
import sql_runner
import nl2sql
import llm

TEST_DB_PATH = "test_independence_db.sqlite"
TEST_META_PATH = "test_independence_meta.json"
TEST_INDEX_PATH = "test_independence_index.faiss"
TEST_MAP_PATH = "test_independence_mapping.json"
TEST_INDEX_META_PATH = "test_independence_idx_meta.json"

ORIGINAL_DB_PATHS = {
    "schema": schema.DB_PATH,
    "quality": quality.DB_PATH,
    "analysis": analysis.DB_PATH,
    "sql_runner": sql_runner.DB_PATH,
}


def cleanup_all_artifacts():
    """Wipes all temporary test databases and vector index artifacts and restores module DB_PATHs."""
    schema.DB_PATH = ORIGINAL_DB_PATHS["schema"]
    quality.DB_PATH = ORIGINAL_DB_PATHS["quality"]
    analysis.DB_PATH = ORIGINAL_DB_PATHS["analysis"]
    sql_runner.DB_PATH = ORIGINAL_DB_PATHS["sql_runner"]

    semantic_embeddings.invalidate_semantic_cache()
    semantic_metadata.invalidate_metadata_cache()
    for p in [TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


def bind_test_db():
    """Binds all backend sub-modules to TEST_DB_PATH."""
    schema.DB_PATH = TEST_DB_PATH
    quality.DB_PATH = TEST_DB_PATH
    analysis.DB_PATH = TEST_DB_PATH
    sql_runner.DB_PATH = TEST_DB_PATH


def setup_dataset_a_enjoysport():
    """Sets up Dataset A: ENJOYSPORT."""
    cleanup_all_artifacts()
    bind_test_db()
    conn = sqlite3.connect(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE ENJOYSPORT (
            Sky TEXT,
            AirTemp TEXT,
            Humidity TEXT,
            Wind TEXT,
            Water TEXT,
            Forecast TEXT,
            EnjoySport TEXT
        );
    """)
    rows = [
        ('Sunny', 'Warm', 'Normal', 'Strong', 'Warm', 'Same', 'Yes'),
        ('Sunny', 'Warm', 'High', 'Strong', 'Warm', 'Same', 'Yes'),
        ('Rainy', 'Cold', 'High', 'Strong', 'Warm', 'Change', 'No'),
        ('Sunny', 'Warm', 'High', 'Strong', 'Cool', 'Change', 'Yes'),
    ]
    cur.executemany("INSERT INTO ENJOYSPORT VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def setup_dataset_b_ecommerce():
    """Sets up Dataset B: Customers and Orders."""
    cleanup_all_artifacts()
    bind_test_db()
    conn = sqlite3.connect(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            customer_name TEXT,
            city TEXT,
            age INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            product TEXT,
            quantity INTEGER,
            price REAL,
            FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
        );
    """)
    customers = [
        (1, 'Alice', 'New York', 28),
        (2, 'Bob', 'San Francisco', 34),
        (3, 'Charlie', 'Chicago', 22),
        (4, 'Diana', 'New York', 41),
    ]
    orders = [
        (101, 1, 'Laptop', 1, 1200.0),
        (102, 1, 'Mouse', 2, 25.0),
        (103, 2, 'Keyboard', 1, 75.0),
        (104, 3, 'Monitor', 2, 300.0),
        (105, 1, 'Headphones', 1, 150.0),
    ]
    cur.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", customers)
    cur.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", orders)
    conn.commit()
    conn.close()


def setup_dataset_c_hr():
    """Sets up Dataset C: Employees and Departments."""
    cleanup_all_artifacts()
    bind_test_db()
    conn = sqlite3.connect(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE departments (
            department_id INTEGER PRIMARY KEY,
            department_name TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE employees (
            employee_id INTEGER PRIMARY KEY,
            name TEXT,
            department_id INTEGER,
            salary REAL,
            FOREIGN KEY (department_id) REFERENCES departments (department_id)
        );
    """)
    departments = [
        (1, 'Engineering'),
        (2, 'Marketing'),
        (3, 'Human Resources'),
    ]
    employees = [
        (1, 'Eve', 1, 110000.0),
        (2, 'Frank', 1, 95000.0),
        (3, 'Grace', 2, 75000.0),
        (4, 'Heidi', 1, 105000.0),
        (5, 'Ivan', 3, 65000.0),
    ]
    cur.executemany("INSERT INTO departments VALUES (?, ?)", departments)
    cur.executemany("INSERT INTO employees VALUES (?, ?, ?, ?)", employees)
    conn.commit()
    conn.close()


class MockMonkeypatch:
    def setattr(self, target, name, value):
        setattr(target, name, value)


def create_schema_aware_mock_llm(active_dataset_id: str):
    """Returns a deterministic LLM handler tailored to the active dataset queries."""
    def mock_ask_llm(prompt: str, task: str = "sql") -> str:
        if task == "interpret":
            return "Analysis complete: Query executed successfully and answered the question."

        # Extract question text from prompt
        q_match = re.search(r"QUESTION:\s*(.*?)(?:\n|$)", prompt, re.IGNORECASE)
        q_text = q_match.group(1).lower() if q_match else prompt.lower()

        # Dataset A queries (ENJOYSPORT)
        if active_dataset_id == "A":
            if "attributes" in q_text:
                return json.dumps({
                    "sql": "SELECT Sky, AirTemp, Humidity, Wind, Water, Forecast, EnjoySport FROM ENJOYSPORT LIMIT 5;",
                    "reasoning": "Retrieve all attribute columns from ENJOYSPORT table."
                })
            elif "equal to yes" in q_text or "yes" in q_text:
                return json.dumps({
                    "sql": "SELECT COUNT(*) AS yes_count FROM ENJOYSPORT WHERE EnjoySport = 'Yes';",
                    "reasoning": "Filter ENJOYSPORT where EnjoySport is Yes."
                })
            elif "how many records" in q_text or "count" in q_text:
                return json.dumps({
                    "sql": "SELECT COUNT(*) AS total_records FROM ENJOYSPORT;",
                    "reasoning": "Count total records in ENJOYSPORT table."
                })

        # Dataset B queries (customers / orders)
        elif active_dataset_id == "B":
            if "how many customers" in q_text:
                return json.dumps({
                    "sql": "SELECT COUNT(*) AS total_customers FROM customers;",
                    "reasoning": "Count total customers in customers table."
                })
            elif "total quantity of products ordered" in q_text or "quantity" in q_text:
                return json.dumps({
                    "sql": "SELECT SUM(quantity) AS total_quantity FROM orders;",
                    "reasoning": "Sum product quantities in orders table."
                })
            elif "most orders" in q_text or "placed the most" in q_text:
                return json.dumps({
                    "sql": "SELECT c.customer_name, COUNT(o.order_id) AS order_count FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_name ORDER BY order_count DESC LIMIT 1;",
                    "reasoning": "Join customers and orders, group by customer_name, order by order_count desc."
                })

        # Dataset C queries (employees / departments)
        elif active_dataset_id == "C":
            if "how many employees" in q_text:
                return json.dumps({
                    "sql": "SELECT COUNT(*) AS total_employees FROM employees;",
                    "reasoning": "Count total employees in employees table."
                })
            elif "average salary" in q_text or "salary" in q_text:
                return json.dumps({
                    "sql": "SELECT AVG(salary) AS avg_salary FROM employees;",
                    "reasoning": "Calculate average salary of employees."
                })
            elif "highest number of employees" in q_text or "department" in q_text:
                return json.dumps({
                    "sql": "SELECT d.department_name, COUNT(e.employee_id) AS emp_count FROM departments d JOIN employees e ON d.department_id = e.department_id GROUP BY d.department_name ORDER BY emp_count DESC LIMIT 1;",
                    "reasoning": "Join departments and employees, count employees per department, order desc."
                })

        # Fallback
        return json.dumps({
            "sql": "SELECT 1;",
            "reasoning": "Fallback select query."
        })

    return mock_ask_llm


def run_pipeline_query(
    question: str,
    active_dataset_id: str,
    mp: MockMonkeypatch,
    expected_allowed_tables: set,
    forbidden_tables: set
) -> Dict[str, Any]:
    """Executes a single natural-language query through the full pipeline with isolation assertions."""
    bind_test_db()
    mp.setattr(llm, "ask_llm", create_schema_aware_mock_llm(active_dataset_id))

    start_t = time.time()
    result = nl2sql.query(
        question=question,
        max_retries=2,
        top_k=8,
        metadata_path=TEST_META_PATH,
        db_path=TEST_DB_PATH,
        use_llm=True,
    )
    latency_ms = int((time.time() - start_t) * 1000)

    # 1. Pipeline success check
    assert result["status"] == "success", f"Query '{question}' failed with status: {result.get('error')}"
    assert result["sql"] is not None and len(result["sql"]) > 0
    assert result["validation"]["valid"] is True
    assert result["execution"]["success"] is True
    assert len(result["explanation"]) > 0

    # 2. Strict Schema Isolation Check on Retrieved Entities
    retrieved_items = result["retrieval"]["items"]
    assert len(retrieved_items) > 0, f"No semantic entities retrieved for: {question}"
    retrieved_tables = set()
    for item in retrieved_items:
        tname = item.get("table")
        retrieved_tables.add(tname)
        assert tname in expected_allowed_tables, f"Stale/Alien table '{tname}' retrieved in Dataset {active_dataset_id}! Allowed: {expected_allowed_tables}"
        assert tname not in forbidden_tables, f"Forbidden table '{tname}' leaked into Dataset {active_dataset_id}!"

    # 3. Strict Schema Isolation Check on Generated SQL
    sql_text = result["sql"]
    for forbidden in forbidden_tables:
        pattern = rf"\b{re.escape(forbidden)}\b"
        assert not re.search(pattern, sql_text, re.IGNORECASE), f"Forbidden entity '{forbidden}' referenced in generated SQL: {sql_text}"

    print(f"\n  [Query] '{question}'")
    print(f"    - Retrieved Tables: {list(retrieved_tables)}")
    print(f"    - SQL: {result['sql']}")
    print(f"    - Validated: {result['validation']['valid']} | Executed: {result['execution']['success']} | Rows: {result['row_count']}")
    print(f"    - Retries: {result['retry_count']} | Latency: {latency_ms}ms")
    print(f"    - Explanation: {result['explanation']}")

    return {
        "question": question,
        "retrieved_tables": list(retrieved_tables),
        "sql": result["sql"],
        "valid": result["validation"]["valid"],
        "validation_errors": result["validation"].get("errors", []),
        "executed": result["execution"]["success"],
        "row_count": result["row_count"],
        "retry_count": result["retry_count"],
        "explanation": result["explanation"],
        "latency_ms": latency_ms,
    }


def test_dataset_a_pipeline(mp: MockMonkeypatch):
    """Evaluates Dataset A (ENJOYSPORT) with 3 questions."""
    print("\n--- Testing Dataset A (ENJOYSPORT) ---")
    setup_dataset_a_enjoysport()
    
    # Generate metadata & FAISS index
    meta = semantic_metadata.generate_all_metadata(db_path=TEST_DB_PATH, metadata_path=TEST_META_PATH, use_llm=False)
    semantic_embeddings.build_index(meta, index_path=TEST_INDEX_PATH, mapping_path=TEST_MAP_PATH, meta_path=TEST_INDEX_META_PATH)

    allowed = {"ENJOYSPORT"}
    forbidden = {"Survey", "Question", "Answer", "AnswerText", "SurveyID", "UserID", "customers", "orders", "employees", "departments"}

    questions = [
        "What attributes are present in the dataset?",
        "How many records are there?",
        "How many records have EnjoySport equal to Yes?",
    ]

    records = []
    for q in questions:
        rec = run_pipeline_query(q, "A", mp, allowed, forbidden)
        records.append(rec)
        assert rec["executed"] is True

    print("  PASS: Dataset A (ENJOYSPORT) Pipeline (3/3 queries verified)")
    return records


def test_dataset_b_pipeline(mp: MockMonkeypatch):
    """Evaluates Dataset B (customers/orders) with 3 questions."""
    print("\n--- Testing Dataset B (Customers & Orders) ---")
    setup_dataset_b_ecommerce()

    meta = semantic_metadata.generate_all_metadata(db_path=TEST_DB_PATH, metadata_path=TEST_META_PATH, use_llm=False)
    semantic_embeddings.build_index(meta, index_path=TEST_INDEX_PATH, mapping_path=TEST_MAP_PATH, meta_path=TEST_INDEX_META_PATH)

    allowed = {"customers", "orders"}
    forbidden = {"ENJOYSPORT", "employees", "departments", "Survey", "Question", "Answer", "AnswerText", "SurveyID", "UserID"}

    questions = [
        "How many customers are there?",
        "What is the total quantity of products ordered?",
        "Which customer has placed the most orders?",
    ]

    records = []
    for q in questions:
        rec = run_pipeline_query(q, "B", mp, allowed, forbidden)
        records.append(rec)
        assert rec["executed"] is True

    print("  PASS: Dataset B (Customers/Orders) Pipeline (3/3 queries verified)")
    return records


def test_dataset_c_pipeline(mp: MockMonkeypatch):
    """Evaluates Dataset C (employees/departments) with 3 questions."""
    print("\n--- Testing Dataset C (Employees & Departments) ---")
    setup_dataset_c_hr()

    meta = semantic_metadata.generate_all_metadata(db_path=TEST_DB_PATH, metadata_path=TEST_META_PATH, use_llm=False)
    semantic_embeddings.build_index(meta, index_path=TEST_INDEX_PATH, mapping_path=TEST_MAP_PATH, meta_path=TEST_INDEX_META_PATH)

    allowed = {"employees", "departments"}
    forbidden = {"ENJOYSPORT", "customers", "orders", "Survey", "Question", "Answer", "AnswerText", "SurveyID", "UserID"}

    questions = [
        "How many employees are there?",
        "What is the average salary?",
        "Which department has the highest number of employees?",
    ]

    records = []
    for q in questions:
        rec = run_pipeline_query(q, "C", mp, allowed, forbidden)
        records.append(rec)
        assert rec["executed"] is True

    print("  PASS: Dataset C (Employees/Departments) Pipeline (3/3 queries verified)")
    return records


def test_sequential_replacement_and_cache_sync(mp: MockMonkeypatch):
    """Step 6: Tests sequential dataset replacement on the exact same database path."""
    print("\n--- Testing Sequential In-Place Dataset Replacement ---")
    sequence = [
        ("A", setup_dataset_a_enjoysport, {"ENJOYSPORT"}, {"customers", "employees", "Survey"}),
        ("B", setup_dataset_b_ecommerce, {"customers", "orders"}, {"ENJOYSPORT", "employees", "Survey"}),
        ("C", setup_dataset_c_hr, {"employees", "departments"}, {"ENJOYSPORT", "customers", "Survey"}),
    ]

    for dataset_id, setup_fn, allowed, forbidden in sequence:
        # Ingest new dataset into TEST_DB_PATH
        setup_fn()

        # Invalidate caches & rebuild
        semantic_embeddings.invalidate_semantic_cache()
        meta = semantic_metadata.generate_all_metadata(db_path=TEST_DB_PATH, metadata_path=TEST_META_PATH, use_llm=False)
        semantic_embeddings.build_index(meta, index_path=TEST_INDEX_PATH, mapping_path=TEST_MAP_PATH, meta_path=TEST_INDEX_META_PATH)

        # Retrieval check
        results = semantic_embeddings.retrieve(
            "Show all data",
            top_k=5,
            metadata_path=TEST_META_PATH,
            index_path=TEST_INDEX_PATH,
            mapping_path=TEST_MAP_PATH,
            meta_path=TEST_INDEX_META_PATH,
            db_path=TEST_DB_PATH
        )
        assert len(results) > 0
        for r in results:
            assert r["table"] in allowed, f"Alien table {r['table']} in dataset {dataset_id}"
            assert r["table"] not in forbidden, f"Forbidden table {r['table']} in dataset {dataset_id}"

    print("  PASS: Sequential Dataset Replacement & Synchronization (A -> B -> C)")


def test_self_correction_and_security(mp: MockMonkeypatch):
    """Step 7: Validates bounded self-correction on invalid candidate and blocks malicious injection."""
    print("\n--- Testing Bounded Self-Correction & Security Rejection ---")
    setup_dataset_b_ecommerce()
    meta = semantic_metadata.generate_all_metadata(db_path=TEST_DB_PATH, metadata_path=TEST_META_PATH, use_llm=False)
    semantic_embeddings.build_index(meta, index_path=TEST_INDEX_PATH, mapping_path=TEST_MAP_PATH, meta_path=TEST_INDEX_META_PATH)
    bind_test_db()

    # 1. Self-Correction Test: Attempt 0 invalid -> Attempt 1 valid
    correction_attempt = {"count": 0}
    def mock_repair_llm(prompt, task="sql"):
        correction_attempt["count"] += 1
        if task == "interpret":
            return "Customer count resolved."
        if correction_attempt["count"] == 1:
            # First attempt produces invalid table name
            return json.dumps({"sql": "SELECT COUNT(*) FROM non_existent_table;", "reasoning": "Wrong table"})
        else:
            # Corrected attempt uses valid table
            return json.dumps({"sql": "SELECT COUNT(*) AS total_customers FROM customers;", "reasoning": "Fixed table name to customers"})

    mp.setattr(llm, "ask_llm", mock_repair_llm)
    result = nl2sql.query(
        question="How many customers are there?",
        max_retries=2,
        metadata_path=TEST_META_PATH,
        db_path=TEST_DB_PATH,
        use_llm=True,
    )

    assert result["status"] == "success"
    assert result["retry_count"] == 1
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["validation"]["valid"] is False
    assert result["attempts"][0]["execution"] is None
    assert result["attempts"][1]["validation"]["valid"] is True
    assert result["attempts"][1]["execution"]["success"] is True

    # 2. Security Test: Malicious statements rejected without execution
    malicious_candidates = [
        "DROP TABLE customers;",
        "DELETE FROM orders WHERE price > 0;",
        "UPDATE customers SET city = 'Hacked';",
        "SELECT * FROM customers; DROP TABLE orders;",
    ]

    for bad_sql in malicious_candidates:
        val_report = sql_validator.validate_sql(bad_sql, db_path=TEST_DB_PATH)
        assert val_report["valid"] is False, f"Malicious query '{bad_sql}' was NOT rejected by SQLGlot!"
        exec_res = nl2sql.execute_validated_sql(bad_sql, db_path=TEST_DB_PATH)
        assert exec_res["success"] is False
        assert "Pre-execution validation failed" in exec_res["error"]

    # Verify tables still exist and data is intact
    conn = sqlite3.connect(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM customers;")
    assert cur.fetchone()[0] == 4
    conn.close()

    print("  PASS: Bounded Self-Correction Loop & Security Attack Rejection")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("RUNNING DATASET INDEPENDENCE & CROSS-SCHEMA VALIDATION SUITE")
    print("="*70)

    mp = MockMonkeypatch()

    try:
        rec_a = test_dataset_a_pipeline(mp)
        rec_b = test_dataset_b_pipeline(mp)
        rec_c = test_dataset_c_pipeline(mp)
        test_sequential_replacement_and_cache_sync(mp)
        test_self_correction_and_security(mp)

        print("\n" + "="*70)
        print("ALL DATASET INDEPENDENCE TESTS COMPLETED WITH 100% PASS RATE")
        print("="*70)

    finally:
        cleanup_all_artifacts()
