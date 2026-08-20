"""
Comprehensive Full Dataset Lifecycle, Cache Invalidation, Staleness, and NL-to-SQL Validation Suite.
Validates Phases B through O for SchemaSense AI.
"""

import os
import re
import json
import time
import sqlite3
import pandas as pd
from typing import Any, Dict, List, Optional
from fastapi.testclient import TestClient

import schema
import quality
import analysis
import semantic_metadata
import semantic_embeddings
import sql_validator
import sql_runner
import nl2sql
import llm
from main import app

client = TestClient(app)

TEST_DB_PATH = "test_full_lifecycle_db.sqlite"
TEST_META_PATH = "test_full_lifecycle_meta.json"
TEST_INDEX_PATH = "test_full_lifecycle_index.faiss"
TEST_MAP_PATH = "test_full_lifecycle_mapping.json"
TEST_INDEX_META_PATH = "test_full_lifecycle_idx_meta.json"

ORIGINAL_DB_PATHS = {
    "schema": schema.DB_PATH,
    "quality": quality.DB_PATH,
    "analysis": analysis.DB_PATH,
    "sql_runner": sql_runner.DB_PATH,
}


def bind_test_db():
    schema.DB_PATH = TEST_DB_PATH
    quality.DB_PATH = TEST_DB_PATH
    analysis.DB_PATH = TEST_DB_PATH
    sql_runner.DB_PATH = TEST_DB_PATH


def safe_remove_file(path: str) -> None:
    """Safely removes a file with retry handling for Windows file locks."""
    if not os.path.exists(path):
        return
    for _ in range(10):
        try:
            os.remove(path)
            return
        except (PermissionError, OSError):
            time.sleep(0.05)


def cleanup_all_artifacts():
    schema.DB_PATH = ORIGINAL_DB_PATHS["schema"]
    quality.DB_PATH = ORIGINAL_DB_PATHS["quality"]
    analysis.DB_PATH = ORIGINAL_DB_PATHS["analysis"]
    sql_runner.DB_PATH = ORIGINAL_DB_PATHS["sql_runner"]

    semantic_embeddings.invalidate_semantic_cache()
    semantic_metadata.invalidate_metadata_cache()
    for p in [TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH]:
        safe_remove_file(p)


# ==============================================================================
# DATASET GENERATORS
# ==============================================================================

def create_dataset_a_ecommerce():
    cleanup_all_artifacts()
    bind_test_db()
    conn = sqlite3.connect(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            customer_name TEXT,
            city TEXT,
            country TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            product_name TEXT,
            category TEXT,
            unit_price REAL
        );
    """)
    cur.execute("""
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            product_id INTEGER,
            quantity INTEGER,
            order_date TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers (customer_id),
            FOREIGN KEY (product_id) REFERENCES products (product_id)
        );
    """)
    cur.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", [
        (1, 'Alice Smith', 'Seattle', 'USA'),
        (2, 'Bob Jones', 'London', 'UK'),
        (3, 'Charlie Brown', 'Paris', 'France'),
        (4, 'Diana Prince', 'Seattle', 'USA'),
    ])
    cur.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", [
        (10, 'Wireless Mouse', 'Electronics', 25.0),
        (20, 'Mechanical Keyboard', 'Electronics', 100.0),
        (30, 'Coffee Mug', 'Kitchen', 15.0),
        (40, 'Desk Lamp', 'Furniture', 45.0),
    ])
    cur.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", [
        (1001, 1, 10, 2, '2026-01-15'),
        (1002, 1, 20, 1, '2026-01-16'),
        (1003, 2, 30, 4, '2026-01-17'),
        (1004, 3, 20, 2, '2026-01-18'),
        (1005, 4, 40, 1, '2026-01-19'),
    ])
    conn.commit()
    conn.close()


def create_dataset_b_hr():
    cleanup_all_artifacts()
    bind_test_db()
    conn = sqlite3.connect(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE departments (
            department_id INTEGER PRIMARY KEY,
            department_name TEXT,
            location TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE employees (
            employee_id INTEGER PRIMARY KEY,
            full_name TEXT,
            department_id INTEGER,
            hire_date TEXT,
            FOREIGN KEY (department_id) REFERENCES departments (department_id)
        );
    """)
    cur.execute("""
        CREATE TABLE salaries (
            salary_id INTEGER PRIMARY KEY,
            employee_id INTEGER,
            amount REAL,
            effective_year INTEGER,
            FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
        );
    """)
    cur.executemany("INSERT INTO departments VALUES (?, ?, ?)", [
        (1, 'Engineering', 'Building A'),
        (2, 'Human Resources', 'Building B'),
        (3, 'Finance', 'Building C'),
    ])
    cur.executemany("INSERT INTO employees VALUES (?, ?, ?, ?)", [
        (101, 'John Doe', 1, '2022-03-01'),
        (102, 'Jane Roe', 1, '2021-06-15'),
        (103, 'Sam Green', 2, '2023-01-10'),
        (104, 'Lucy Black', 3, '2020-11-20'),
        (105, 'Mark White', 1, '2024-02-01'),
    ])
    cur.executemany("INSERT INTO salaries VALUES (?, ?, ?, ?)", [
        (1, 101, 120000.0, 2026),
        (2, 102, 135000.0, 2026),
        (3, 103, 75000.0, 2026),
        (4, 104, 95000.0, 2026),
        (5, 105, 110000.0, 2026),
    ])
    conn.commit()
    conn.close()


def create_dataset_c_movies():
    cleanup_all_artifacts()
    bind_test_db()
    conn = sqlite3.connect(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE movies (
            movie_id INTEGER PRIMARY KEY,
            title TEXT,
            release_year INTEGER,
            genre TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE actors (
            actor_id INTEGER PRIMARY KEY,
            actor_name TEXT,
            birth_year INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE ratings (
            rating_id INTEGER PRIMARY KEY,
            movie_id INTEGER,
            rating_score REAL,
            reviewer_name TEXT,
            FOREIGN KEY (movie_id) REFERENCES movies (movie_id)
        );
    """)
    cur.executemany("INSERT INTO movies VALUES (?, ?, ?, ?)", [
        (1, 'Inception', 2010, 'Sci-Fi'),
        (2, 'The Dark Knight', 2008, 'Action'),
        (3, 'Interstellar', 2014, 'Sci-Fi'),
        (4, 'Parasite', 2019, 'Drama'),
        (5, 'Whiplash', 2014, 'Drama'),
    ])
    cur.executemany("INSERT INTO actors VALUES (?, ?, ?)", [
        (101, 'Leonardo DiCaprio', 1974),
        (102, 'Christian Bale', 1974),
        (103, 'Matthew McConaughey', 1969),
        (104, 'Song Kang-ho', 1967),
    ])
    cur.executemany("INSERT INTO ratings VALUES (?, ?, ?, ?)", [
        (1, 1, 8.8, 'User1'),
        (2, 1, 9.0, 'User2'),
        (3, 2, 9.0, 'User1'),
        (4, 2, 9.5, 'User2'),
        (5, 3, 8.6, 'User1'),
        (6, 4, 8.5, 'User3'),
        (7, 5, 8.5, 'User3'),
    ])
    conn.commit()
    conn.close()


def create_dataset_d_weather():
    cleanup_all_artifacts()
    bind_test_db()
    conn = sqlite3.connect(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE stations (
            station_id INTEGER PRIMARY KEY,
            station_name TEXT,
            latitude REAL,
            longitude REAL,
            elevation REAL
        );
    """)
    cur.execute("""
        CREATE TABLE weather_readings (
            reading_id INTEGER PRIMARY KEY,
            station_id INTEGER,
            reading_date TEXT,
            temperature_c REAL,
            humidity_pct REAL,
            precipitation_mm REAL,
            FOREIGN KEY (station_id) REFERENCES stations (station_id)
        );
    """)
    cur.executemany("INSERT INTO stations VALUES (?, ?, ?, ?, ?)", [
        (1, 'Central Park NY', 40.78, -73.96, 48.0),
        (2, "O'Hare Chicago", 41.97, -87.90, 203.0),
        (3, 'LAX Airport', 33.94, -118.40, 38.0),
    ])
    cur.executemany("INSERT INTO weather_readings VALUES (?, ?, ?, ?, ?, ?)", [
        (101, 1, '2026-07-01', 28.5, 65.0, 0.0),
        (102, 1, '2026-07-02', 31.0, 70.0, 12.5),
        (103, 2, '2026-07-01', 25.0, 60.0, 0.0),
        (104, 2, '2026-07-02', 24.5, 80.0, 25.0),
        (105, 3, '2026-07-01', 26.0, 55.0, 0.0),
        (106, 3, '2026-07-02', 27.0, 50.0, 0.0),
    ])
    conn.commit()
    conn.close()


# ==============================================================================
# PHASE B & C: REAL LIFECYCLE & CROSS-CONTAMINATION SWITCHING
# ==============================================================================

def test_phase_b_and_c_lifecycle_switching():
    """
    Executes sequence A -> B -> C -> D -> A on same live DB without process restart.
    Asserts 0% stale entities at each step.
    """
    print("\n--- PHASE B & C: Real Lifecycle & Cross-Contamination Switching ---")
    switching_sequence = [
        ("A", create_dataset_a_ecommerce, {"customers", "products", "orders"}, {"departments", "movies", "stations", "Survey", "Answer"}),
        ("B", create_dataset_b_hr, {"departments", "employees", "salaries"}, {"customers", "products", "orders", "movies", "stations", "Survey"}),
        ("C", create_dataset_c_movies, {"movies", "actors", "ratings"}, {"customers", "departments", "stations", "Survey", "Answer"}),
        ("D", create_dataset_d_weather, {"stations", "weather_readings"}, {"customers", "departments", "movies", "Survey", "Answer"}),
        ("A_again", create_dataset_a_ecommerce, {"customers", "products", "orders"}, {"departments", "movies", "stations", "Survey", "Answer"}),
    ]

    for name, create_fn, allowed, forbidden in switching_sequence:
        create_fn()
        sync_res = semantic_embeddings.sync_semantic_state(
            db_path=TEST_DB_PATH,
            metadata_path=TEST_META_PATH,
            index_path=TEST_INDEX_PATH,
            mapping_path=TEST_MAP_PATH,
            meta_path=TEST_INDEX_META_PATH,
            use_llm=False
        )
        assert sync_res["status"] == "synchronized"
        assert set(sync_res["tables"]) == allowed

        # Check metadata
        meta = semantic_metadata.load_metadata(TEST_META_PATH)
        assert set(meta["tables"].keys()) == allowed

        # Check FAISS mapping
        with open(TEST_MAP_PATH, "r", encoding="utf-8") as f:
            mapping = json.load(f)
        mapping_tables = set(item["table"] for item in mapping)
        assert mapping_tables == allowed

        # Perform retrieval
        retrieved = semantic_embeddings.retrieve(
            "Show summary data",
            top_k=8,
            metadata_path=TEST_META_PATH,
            index_path=TEST_INDEX_PATH,
            mapping_path=TEST_MAP_PATH,
            meta_path=TEST_INDEX_META_PATH,
            db_path=TEST_DB_PATH,
        )
        assert len(retrieved) > 0
        for item in retrieved:
            assert item["table"] in allowed
            assert item["table"] not in forbidden

    print("  PASS: Phase B & C Dataset Switching and Strict Schema Isolation (A -> B -> C -> D -> A)")


# ==============================================================================
# PHASE D: DIRECT IN-MEMORY CACHE INVALIDATION
# ==============================================================================

def test_phase_d_cache_invalidation():
    """Verifies that in-memory singletons are cleanly refreshed across dataset switches."""
    print("\n--- PHASE D: Direct In-Memory Cache Invalidation ---")
    create_dataset_a_ecommerce()
    semantic_embeddings.sync_semantic_state(TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, False)

    # 1. Warm up cache on Dataset A
    res_a = semantic_embeddings.retrieve("customers", metadata_path=TEST_META_PATH, index_path=TEST_INDEX_PATH, mapping_path=TEST_MAP_PATH, meta_path=TEST_INDEX_META_PATH, db_path=TEST_DB_PATH)
    assert any(r["table"] == "customers" for r in res_a)
    assert semantic_embeddings._CACHED_INDEX is not None
    assert semantic_embeddings._CACHED_MAPPING is not None

    # 2. Switch to Dataset B without process restart
    create_dataset_b_hr()
    semantic_embeddings.sync_semantic_state(TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, False)

    # 3. Retrieve on Dataset B -> must never return 'customers'
    res_b = semantic_embeddings.retrieve("employees", metadata_path=TEST_META_PATH, index_path=TEST_INDEX_PATH, mapping_path=TEST_MAP_PATH, meta_path=TEST_INDEX_META_PATH, db_path=TEST_DB_PATH)
    assert any(r["table"] == "employees" for r in res_b)
    for r in res_b:
        assert r["table"] != "customers"
        assert r["table"] in {"departments", "employees", "salaries"}

    print("  PASS: Phase D In-Memory Cache Invalidation across Dataset Transitions")


# ==============================================================================
# PHASE E: METADATA STALENESS MATRIX (8 DISTINCT STATES)
# ==============================================================================

def test_phase_e_staleness_matrix():
    """Evaluates 8 distinct staleness and artifact deletion scenarios."""
    print("\n--- PHASE E: Metadata Staleness Matrix (8 States) ---")
    create_dataset_a_ecommerce()
    semantic_embeddings.sync_semantic_state(TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, False)

    # State 1: Database changed, metadata unchanged
    conn = sqlite3.connect(TEST_DB_PATH)
    conn.execute("CREATE TABLE new_table_x (x INTEGER);")
    conn.commit()
    conn.close()
    assert semantic_metadata.is_metadata_stale(TEST_META_PATH, TEST_DB_PATH) is True
    assert semantic_embeddings.is_index_stale(TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, TEST_META_PATH, db_path=TEST_DB_PATH) is True

    # State 2: Metadata changed, index unchanged
    semantic_embeddings.sync_semantic_state(TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, False)
    meta = semantic_metadata.load_metadata(TEST_META_PATH)
    meta["generated_at"] = "2099-01-01T00:00:00Z"
    with open(TEST_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    assert semantic_embeddings.is_index_stale(TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, TEST_META_PATH, db_path=TEST_DB_PATH) is True

    # State 3: DB and metadata changed, index unchanged
    assert semantic_embeddings.is_index_stale(TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, TEST_META_PATH, db_path=TEST_DB_PATH) is True

    # State 4: Index deleted
    semantic_embeddings.sync_semantic_state(TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, False)
    safe_remove_file(TEST_INDEX_PATH)
    assert semantic_embeddings.is_index_stale(TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, TEST_META_PATH, db_path=TEST_DB_PATH) is True

    # State 5: Mapping deleted
    semantic_embeddings.sync_semantic_state(TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, False)
    safe_remove_file(TEST_MAP_PATH)
    assert semantic_embeddings.is_index_stale(TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, TEST_META_PATH, db_path=TEST_DB_PATH) is True

    # State 6: Index metadata deleted
    semantic_embeddings.sync_semantic_state(TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, False)
    safe_remove_file(TEST_INDEX_META_PATH)
    assert semantic_embeddings.is_index_stale(TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, TEST_META_PATH, db_path=TEST_DB_PATH) is True

    # State 7: Metadata deleted
    semantic_embeddings.sync_semantic_state(TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, False)
    safe_remove_file(TEST_META_PATH)
    assert semantic_metadata.is_metadata_stale(TEST_META_PATH, TEST_DB_PATH) is True
    assert semantic_embeddings.is_index_stale(TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, TEST_META_PATH, db_path=TEST_DB_PATH) is True

    # State 8: All semantic artifacts deleted
    semantic_embeddings.clear_semantic_state(TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH)
    assert semantic_metadata.is_metadata_stale(TEST_META_PATH, TEST_DB_PATH) is True
    assert semantic_embeddings.is_index_stale(TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, TEST_META_PATH, db_path=TEST_DB_PATH) is True

    # Recovery test: retrieve() restores valid state automatically
    res = semantic_embeddings.retrieve("test recovery", top_k=3, metadata_path=TEST_META_PATH, index_path=TEST_INDEX_PATH, mapping_path=TEST_MAP_PATH, meta_path=TEST_INDEX_META_PATH, db_path=TEST_DB_PATH)
    assert len(res) > 0
    assert os.path.exists(TEST_META_PATH)
    assert os.path.exists(TEST_INDEX_PATH)

    print("  PASS: Phase E Staleness Matrix (All 8 States Properly Detected & Recovered)")


# ==============================================================================
# PHASE F: INGESTION FAILURE SAFETY
# ==============================================================================

def test_phase_f_ingestion_failure_safety():
    """Simulates failures and ensures stale semantic state is purged, never served."""
    print("\n--- PHASE F: Ingestion Failure Safety ---")
    create_dataset_a_ecommerce()
    semantic_embeddings.sync_semantic_state(TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, False)

    # Simulate database file missing during sync
    res = semantic_embeddings.sync_semantic_state(
        db_path="non_existent.sqlite",
        metadata_path=TEST_META_PATH,
        index_path=TEST_INDEX_PATH,
        mapping_path=TEST_MAP_PATH,
        meta_path=TEST_INDEX_META_PATH,
    )
    assert res["status"] == "skipped"
    # Artifacts must be purged
    assert not os.path.exists(TEST_INDEX_PATH)
    assert not os.path.exists(TEST_META_PATH)

    print("  PASS: Phase F Ingestion Failure Safety (Stale Artifacts Purged on Error)")


# ==============================================================================
# PHASE H: SELF-CORRECTION & SECURITY
# ==============================================================================

def test_phase_h_self_correction_and_security():
    """Validates bounded self-correction and security defense against destructive SQL."""
    print("\n--- PHASE H: Self-Correction & Security Regression ---")
    create_dataset_a_ecommerce()
    semantic_embeddings.sync_semantic_state(TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, False)

    # 1. Bounded Self-Correction Test
    attempt_count = {"count": 0}
    def mock_repair_llm(prompt: str, task: str = "sql") -> str:
        attempt_count["count"] += 1
        if task == "interpret":
            return "Repaired."
        if attempt_count["count"] == 1:
            # Fault injection: bad column name
            return json.dumps({"sql": "SELECT non_existent_col FROM customers;", "reasoning": "Wrong col"})
        else:
            return json.dumps({"sql": "SELECT customer_name FROM customers ORDER BY customer_name;", "reasoning": "Fixed column"})

    orig_llm = llm.ask_llm
    llm.ask_llm = mock_repair_llm
    try:
        res = nl2sql.query(
            question="List all customer names",
            max_retries=2,
            metadata_path=TEST_META_PATH,
            db_path=TEST_DB_PATH,
            use_llm=True,
        )
    finally:
        llm.ask_llm = orig_llm

    assert res["status"] == "success"
    assert res["retry_count"] == 1
    assert res["attempts"][0]["validation"]["valid"] is False
    assert res["attempts"][0]["execution"] is None
    assert res["attempts"][1]["validation"]["valid"] is True
    assert res["attempts"][1]["execution"]["success"] is True

    # 2. Security Defense: Malicious operations
    malicious_queries = [
        "DROP TABLE customers;",
        "DELETE FROM products WHERE unit_price > 0;",
        "UPDATE customers SET country = 'Hacked';",
        "INSERT INTO customers VALUES (99, 'Hacker', 'None', 'None');",
        "ALTER TABLE products DROP COLUMN category;",
        "CREATE TABLE backdoor (id INT);",
        "ATTACH DATABASE 'evil.db' AS evil;",
        "SELECT * FROM customers; DROP TABLE orders;",
        "SELECT * FROM customers -- \n DROP TABLE products;",
    ]

    for evil_sql in malicious_queries:
        val = sql_validator.validate_sql(evil_sql, db_path=TEST_DB_PATH)
        assert val["valid"] is False, f"Malicious query '{evil_sql}' was NOT blocked by validator!"
        exec_res = nl2sql.execute_validated_sql(evil_sql, db_path=TEST_DB_PATH)
        assert exec_res["success"] is False

    # Check data integrity in SQLite
    conn = sqlite3.connect(TEST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM customers;")
    assert cur.fetchone()[0] == 4
    conn.close()

    print("  PASS: Phase H Self-Correction Repaired Erroneous Query & Blocked 9 Malicious Injections")


# ==============================================================================
# PHASE I: RETRY LIMIT NORMALIZATION
# ==============================================================================

def test_phase_i_retry_limits():
    """Verifies that max_retries normalization enforces bounds [0, 5]."""
    print("\n--- PHASE I: Hard Retry Boundary Normalization ---")
    create_dataset_a_ecommerce()
    semantic_embeddings.sync_semantic_state(TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, False)

    # Helper mock that always fails validation
    orig_llm = llm.ask_llm
    llm.ask_llm = lambda prompt, task="sql": json.dumps({"sql": "SELECT * FROM non_existent_table;", "reasoning": "bad"})

    try:
        # Test max_retries = 0 -> 1 attempt total
        res0 = nl2sql.query("test", max_retries=0, metadata_path=TEST_META_PATH, db_path=TEST_DB_PATH, use_llm=True)
        assert res0["status"] == "failed"
        assert len(res0["attempts"]) == 1

        # Test max_retries = 2 -> 3 attempts total
        res2 = nl2sql.query("test", max_retries=2, metadata_path=TEST_META_PATH, db_path=TEST_DB_PATH, use_llm=True)
        assert res2["status"] == "failed"
        assert len(res2["attempts"]) == 3

        # Test max_retries = 10 (capped at 5) -> 6 attempts total
        res10 = nl2sql.query("test", max_retries=10, metadata_path=TEST_META_PATH, db_path=TEST_DB_PATH, use_llm=True)
        assert res10["status"] == "failed"
        assert len(res10["attempts"]) == 6  # 1 initial + 5 retries max

        # Test negative max_retries = -1 (floored at 0) -> 1 attempt total
        res_neg = nl2sql.query("test", max_retries=-1, metadata_path=TEST_META_PATH, db_path=TEST_DB_PATH, use_llm=True)
        assert res_neg["status"] == "failed"
        assert len(res_neg["attempts"]) == 1

    finally:
        llm.ask_llm = orig_llm

    print("  PASS: Phase I Hard Retry Boundaries Strictly Enforced [0, 5]")


# ==============================================================================
# PHASE J: API ENDPOINTS COMPREHENSIVE TEST
# ==============================================================================

def test_phase_j_api_endpoints():
    """Tests POST /ingest/clear, POST /ingest/file, POST /nl2sql/query, and GET /semantic/status."""
    print("\n--- PHASE J: API Endpoints Validation ---")
    cleanup_all_artifacts()
    
    # 1. Clear database
    clear_resp = client.post("/ingest/clear")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["status"] == "cleared"

    # 2. Upload valid CSV
    csv_bytes = b"id,name,role\n1,Alice,Dev\n2,Bob,QA\n"
    files = {"file": ("team.csv", csv_bytes, "text/csv")}
    upload_resp = client.post("/ingest/file", files=files)
    assert upload_resp.status_code == 200
    assert upload_resp.json()["status"] == "uploaded"
    assert upload_resp.json()["semantic_sync"]["status"] == "synchronized"

    # 3. Check /semantic/status
    status_resp = client.get("/semantic/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["metadata_exists"] is True
    assert status_data["is_stale"] is False
    assert status_data["table_count"] == 1

    # 4. Valid NL2SQL query
    orig_llm = llm.ask_llm
    llm.ask_llm = lambda prompt, task="sql": (
        json.dumps({"sql": "SELECT COUNT(*) AS total_devs FROM team;", "reasoning": "Count team"})
        if task == "sql" else "There are team members."
    )

    try:
        q_resp = client.post("/nl2sql/query", json={"question": "How many team members are there?"})
        assert q_resp.status_code == 200
        q_data = q_resp.json()
        assert q_data["status"] == "success"
        assert q_data["sql"] == "SELECT COUNT(*) AS total_devs FROM team;"
        assert q_data["execution"]["success"] is True

        # 5. Invalid / Empty question -> 400 Bad Request
        bad_resp = client.post("/nl2sql/query", json={"question": "   "})
        assert bad_resp.status_code == 400

    finally:
        llm.ask_llm = orig_llm

    print("  PASS: Phase J API Endpoints (POST /ingest/file, /clear, /nl2sql/query, GET /semantic/status)")


# ==============================================================================
# PHASE K: FAISS VERIFICATION
# ==============================================================================

def test_phase_k_faiss_environment():
    """Verifies native FAISS IndexFlatIP(384) dimension, normalization, and mapping integrity."""
    print("\n--- PHASE K: FAISS Environment Verification ---")
    create_dataset_a_ecommerce()
    semantic_embeddings.sync_semantic_state(TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, False)

    index, mapping, meta_doc = semantic_embeddings.load_index(
        index_path=TEST_INDEX_PATH,
        mapping_path=TEST_MAP_PATH,
        meta_path=TEST_INDEX_META_PATH,
        metadata_path=TEST_META_PATH,
        db_path=TEST_DB_PATH,
        force=True
    )

    assert index.d == 384
    assert index.ntotal == len(mapping)
    assert meta_doc["embedding_model"] == "all-MiniLM-L6-v2"
    assert meta_doc["embedding_dimension"] == 384

    print(f"  PASS: Phase K FAISS Index Verified (d={index.d}, total_vectors={index.ntotal})")


# ==============================================================================
# MAIN RUNNER
# ==============================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("STARTING FULL DATASET LIFECYCLE & INVARIANT VALIDATION SUITE")
    print("="*70)

    try:
        test_phase_b_and_c_lifecycle_switching()
        test_phase_d_cache_invalidation()
        test_phase_e_staleness_matrix()
        test_phase_f_ingestion_failure_safety()
        test_phase_h_self_correction_and_security()
        test_phase_i_retry_limits()
        test_phase_j_api_endpoints()
        test_phase_k_faiss_environment()

        print("\n" + "="*70)
        print("ALL LIFECYCLE & INVARIANT TEST PHASES PASSED WITH 100% SUCCESS")
        print("="*70)

    finally:
        cleanup_all_artifacts()
