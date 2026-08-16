"""
Comprehensive test suite for semantic_metadata module and endpoints.
Can be run directly via python test_semantic_metadata.py or via pytest.
"""

import os
import json
import sqlite3
import tempfile
from fastapi.testclient import TestClient

import main
import semantic_metadata
import llm


def create_temp_sqlite_db():
    """Creates a temporary SQLite database with multiple tables, FKs, nulls, and types."""
    f = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    db_path = f.name
    f.close()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. Parent Table (Surveys)
    cur.execute("""
        CREATE TABLE surveys (
            survey_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TIMESTAMP,
            is_active INTEGER DEFAULT 1
        );
    """)

    # 2. Child Table with explicit FK (Questions)
    cur.execute("""
        CREATE TABLE questions (
            question_id INTEGER PRIMARY KEY,
            survey_id INTEGER,
            question_text TEXT,
            category TEXT,
            max_score REAL,
            FOREIGN KEY (survey_id) REFERENCES surveys(survey_id)
        );
    """)

    # 3. Table with inferred relationship, null-heavy, and numeric metrics (Responses)
    cur.execute("""
        CREATE TABLE responses (
            response_id INTEGER PRIMARY KEY,
            question_id INTEGER,
            user_identifier TEXT,
            score REAL,
            notes TEXT,
            submitted_date TEXT
        );
    """)

    # 4. Standalone Table without relationships
    cur.execute("""
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            val TEXT
        );
    """)

    # 5. Empty Table (0 rows)
    cur.execute("""
        CREATE TABLE audit_logs (
            log_id INTEGER PRIMARY KEY,
            event_name TEXT,
            logged_at TIMESTAMP
        );
    """)

    # Populate sample data
    cur.executemany("INSERT INTO surveys VALUES (?, ?, ?, ?)", [
        (1, "Customer Satisfaction 2026", "2026-01-10 10:00:00", 1),
        (2, "Product Usability Study", "2026-02-15 14:30:00", 1),
    ])

    cur.executemany("INSERT INTO questions VALUES (?, ?, ?, ?, ?)", [
        (101, 1, "How satisfied are you with the platform?", "satisfaction", 10.0),
        (102, 1, "How likely are you to recommend us?", "nps", 10.0),
        (103, 2, "How easy was the onboarding flow?", "usability", 5.0),
    ])

    cur.executemany("INSERT INTO responses VALUES (?, ?, ?, ?, ?, ?)", [
        (1001, 101, "user_alpha", 9.5, "Great experience", "2026-02-01"),
        (1002, 101, "user_beta", 8.0, None, "2026-02-02"),
        (1003, 102, "user_alpha", 10.0, "Very fast", "2026-02-03"),
        (1004, 103, "user_gamma", 4.0, None, "2026-02-16"),
        (1005, 103, "user_delta", None, None, None), # null-heavy row
    ])

    cur.executemany("INSERT INTO settings VALUES (?, ?)", [
        ("app_theme", "dark"),
        ("timeout_seconds", "60"),
    ])

    conn.commit()
    conn.close()

    return db_path


def test_evidence_collection_multi_tables():
    """Verifies evidence collection across multiple tables with diverse schemas."""
    db_path = create_temp_sqlite_db()
    try:
        evidence = semantic_metadata.collect_table_evidence("surveys", db_path=db_path)
        assert evidence["table_name"] == "surveys"
        assert evidence["row_count"] == 2
        assert evidence["column_count"] == 4
        assert "survey_id" in evidence["columns"]
        assert evidence["columns"]["survey_id"]["is_pk"] is True
        assert "quality" in evidence
        assert "statistics" in evidence
        print("  PASS: test_evidence_collection_multi_tables")
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_evidence_collection_empty_table():
    """Verifies evidence collection handles empty tables (0 rows) gracefully."""
    db_path = create_temp_sqlite_db()
    try:
        evidence = semantic_metadata.collect_table_evidence("audit_logs", db_path=db_path)
        assert evidence["table_name"] == "audit_logs"
        assert evidence["row_count"] == 0
        assert evidence["column_count"] == 3
        assert evidence["columns"]["log_id"]["is_pk"] is True
        assert evidence["columns"]["event_name"]["sample_values"] == []
        print("  PASS: test_evidence_collection_empty_table")
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_evidence_collection_null_heavy_and_types():
    """Verifies handling of NULL-heavy and mixed data types."""
    db_path = create_temp_sqlite_db()
    try:
        evidence = semantic_metadata.collect_table_evidence("responses", db_path=db_path)
        assert "notes" in evidence["columns"]
        assert evidence["columns"]["notes"]["null_percentage"] > 0
        assert "score" in evidence["columns"]
        assert len(evidence["columns"]["score"]["sample_values"]) > 0
        print("  PASS: test_evidence_collection_null_heavy_and_types")
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_deterministic_fallback_generation():
    """Verifies deterministic fallback metadata when use_llm=False."""
    db_path = create_temp_sqlite_db()
    try:
        evidence = semantic_metadata.collect_table_evidence("surveys", db_path=db_path)
        gen = semantic_metadata.generate_table_metadata("surveys", evidence, use_llm=False)
        assert gen["source"] == "fallback"
        assert gen["model"] == "deterministic_fallback"
        assert gen["business_domain"] == "surveys"
        assert "survey_id" in gen["columns"]
        assert gen["columns"]["survey_id"]["business_role"] == "primary_key"
        assert len(gen["semantic_aliases"]) > 0
        assert len(gen["common_questions"]) > 0
        print("  PASS: test_deterministic_fallback_generation")
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_llm_metadata_generation_mock():
    """Verifies structured LLM metadata parsing and enrichment using mock ask_llm."""
    db_path = create_temp_sqlite_db()
    orig_ask = llm.ask_llm
    try:
        mock_llm_json = json.dumps({
            "table_description": "Stores high-level survey definitions and lifecycle metadata.",
            "business_domain": "surveys",
            "semantic_aliases": ["surveys", "questionnaires", "poll forms"],
            "columns": {
                "survey_id": {
                    "description": "Unique survey identifier",
                    "semantic_aliases": ["survey id", "form id"],
                    "business_role": "primary_key"
                },
                "title": {
                    "description": "Display title of the survey",
                    "semantic_aliases": ["survey name", "topic"],
                    "business_role": "dimension"
                }
            },
            "common_questions": [
                "What active surveys exist?",
                "When was the latest survey created?"
            ]
        })
        llm.ask_llm = lambda prompt, task="summary": mock_llm_json

        evidence = semantic_metadata.collect_table_evidence("surveys", db_path=db_path)
        gen = semantic_metadata.generate_table_metadata("surveys", evidence, use_llm=True)

        assert gen["source"] == "llm"
        assert gen["table_description"] == "Stores high-level survey definitions and lifecycle metadata."
        assert gen["columns"]["survey_id"]["business_role"] == "primary_key"
        assert "What active surveys exist?" in gen["common_questions"]
        print("  PASS: test_llm_metadata_generation_mock")
    finally:
        llm.ask_llm = orig_ask
        if os.path.exists(db_path):
            os.remove(db_path)


def test_llm_malformed_json_resilience():
    """Verifies that malformed LLM responses safely fallback to deterministic metadata without crashing."""
    db_path = create_temp_sqlite_db()
    orig_ask = llm.ask_llm
    try:
        llm.ask_llm = lambda prompt, task="summary": "INVALID NOT JSON <<<>>>"

        evidence = semantic_metadata.collect_table_evidence("surveys", db_path=db_path)
        gen = semantic_metadata.generate_table_metadata("surveys", evidence, use_llm=True)

        assert gen["source"] == "fallback"
        assert gen["model"] == "deterministic_fallback"
        assert "survey_id" in gen["columns"]
        print("  PASS: test_llm_malformed_json_resilience")
    finally:
        llm.ask_llm = orig_ask
        if os.path.exists(db_path):
            os.remove(db_path)


def test_atomic_file_write_and_load():
    """Verifies full metadata generation, atomic persistence, and loading."""
    db_path = create_temp_sqlite_db()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        meta_path = f.name
    if os.path.exists(meta_path):
        os.remove(meta_path)

    try:
        doc = semantic_metadata.generate_all_metadata(
            db_path=db_path,
            metadata_path=meta_path,
            use_llm=False
        )

        assert os.path.exists(meta_path)
        assert doc["table_count"] == 5
        assert "surveys" in doc["tables"]
        assert "audit_logs" in doc["tables"]
        assert "observed" in doc["tables"]["surveys"]
        assert "generated" in doc["tables"]["surveys"]

        loaded = semantic_metadata.load_metadata(meta_path)
        assert loaded is not None
        assert loaded["table_count"] == 5
        assert loaded["database_fingerprint"]["table_count"] == 5

        assert semantic_metadata.is_metadata_stale(meta_path, db_path) is False
        age = semantic_metadata.get_metadata_age(meta_path)
        assert age is not None and age >= 0.0
        print("  PASS: test_atomic_file_write_and_load")
    finally:
        if os.path.exists(meta_path):
            os.remove(meta_path)
        if os.path.exists(db_path):
            os.remove(db_path)


def test_staleness_detection_on_db_change():
    """Verifies that modifying the database marks the metadata as stale."""
    db_path = create_temp_sqlite_db()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        meta_path = f.name

    try:
        semantic_metadata.generate_all_metadata(
            db_path=db_path,
            metadata_path=meta_path,
            use_llm=False
        )
        assert semantic_metadata.is_metadata_stale(meta_path, db_path) is False

        # Alter DB by adding a table
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE new_table (id INT);")
        conn.commit()
        conn.close()

        assert semantic_metadata.is_metadata_stale(meta_path, db_path) is True
        print("  PASS: test_staleness_detection_on_db_change")
    finally:
        if os.path.exists(meta_path):
            os.remove(meta_path)
        if os.path.exists(db_path):
            os.remove(db_path)


def test_api_semantic_endpoints():
    """Tests the FastAPI endpoints GET /semantic/status and POST /semantic/generate."""
    client = TestClient(main.app)

    # 1. GET /semantic/status
    res_status = client.get("/semantic/status")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert "metadata_exists" in status_data
    assert "is_stale" in status_data

    # 2. POST /semantic/generate (with use_llm=False for deterministic test)
    res_gen = client.post("/semantic/generate", json={"use_llm": False})
    assert res_gen.status_code == 200
    gen_data = res_gen.json()
    assert gen_data["status"] == "success"
    assert gen_data["table_count"] > 0

    # 3. GET /semantic/status again (should now exist)
    res_status2 = client.get("/semantic/status")
    assert res_status2.status_code == 200
    status_data2 = res_status2.json()
    assert status_data2["metadata_exists"] is True
    assert status_data2["table_count"] > 0
    print("  PASS: test_api_semantic_endpoints")


if __name__ == "__main__":
    print("\nRunning Semantic Metadata Test Suite...")
    test_evidence_collection_multi_tables()
    test_evidence_collection_empty_table()
    test_evidence_collection_null_heavy_and_types()
    test_deterministic_fallback_generation()
    test_llm_metadata_generation_mock()
    test_llm_malformed_json_resilience()
    test_atomic_file_write_and_load()
    test_staleness_detection_on_db_change()
    test_api_semantic_endpoints()
    print("\nALL 9 TEST SUITES PASSED SUCCESSFULLY!\n")
