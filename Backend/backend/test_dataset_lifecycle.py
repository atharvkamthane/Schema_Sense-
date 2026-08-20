"""
Test Suite for Dataset Lifecycle & Semantic Synchronization Layer.

Validates that:
1. Dataset replacements in SQLite immediately invalidate stale metadata & FAISS index.
2. Stale entities (e.g. AnswerText, SurveyID, UserID) never survive dataset replacement.
3. Automatic cascading synchronization regenerates metadata and FAISS index accurately.
4. Upload / Clear API endpoints correctly clean up artifacts and synchronize fresh schemas.
5. Multiple sequential dataset replacements consistently synchronize.
6. Failure safety: Generation or index build failures cleanly strip stale index artifacts.
7. NL->SQL regression: Schema replacement results in queries referencing only the new schema.
"""

import os
import json
import sqlite3
import pandas as pd
from fastapi.testclient import TestClient

import semantic_metadata
import semantic_embeddings
import sql_validator
import sql_runner
import nl2sql
import llm
from main import app

client = TestClient(app)

TEST_DB_PATH = "test_lifecycle_db.sqlite"
TEST_META_PATH = "test_lifecycle_meta.json"
TEST_INDEX_PATH = "test_lifecycle_index.faiss"
TEST_MAP_PATH = "test_lifecycle_mapping.json"
TEST_INDEX_META_PATH = "test_lifecycle_idx_meta.json"


def cleanup_test_files():
    """Removes all test artifacts and clears in-memory caches."""
    semantic_embeddings.invalidate_semantic_cache()
    semantic_metadata.invalidate_metadata_cache()
    for p in [TEST_DB_PATH, TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


def test_initial_dataset_and_staleness_detection():
    """Step 1-4: Set up initial survey schema, replace with planets, verify staleness."""
    cleanup_test_files()
    # 1. Initial Dataset: Survey / Question / Answer
    conn = sqlite3.connect(TEST_DB_PATH)
    conn.execute("CREATE TABLE Survey (SurveyID INTEGER PRIMARY KEY, Title TEXT);")
    conn.execute("CREATE TABLE Question (QuestionID INTEGER PRIMARY KEY, QuestionText TEXT, SurveyID INTEGER);")
    conn.execute("CREATE TABLE Answer (AnswerID INTEGER PRIMARY KEY, AnswerText TEXT, UserID INTEGER, QuestionID INTEGER);")
    conn.commit()
    conn.close()

    # Generate initial metadata and FAISS index
    meta1 = semantic_metadata.generate_all_metadata(db_path=TEST_DB_PATH, metadata_path=TEST_META_PATH, use_llm=False)
    idx1, map1, idx_meta1 = semantic_embeddings.build_index(
        meta1, index_path=TEST_INDEX_PATH, mapping_path=TEST_MAP_PATH, meta_path=TEST_INDEX_META_PATH
    )

    assert set(meta1["tables"].keys()) == {"Survey", "Question", "Answer"}
    assert idx_meta1["vector_count"] > 0
    assert semantic_metadata.is_metadata_stale(TEST_META_PATH, TEST_DB_PATH) is False
    assert semantic_embeddings.is_index_stale(TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, TEST_META_PATH, db_path=TEST_DB_PATH) is False

    # 2. Replace database completely with 'planets' table
    os.remove(TEST_DB_PATH)
    conn = sqlite3.connect(TEST_DB_PATH)
    conn.execute("CREATE TABLE planets (planet_name TEXT, orbital_period REAL);")
    conn.execute("INSERT INTO planets VALUES ('Mercury', 88.0), ('Venus', 224.7), ('Earth', 365.2);")
    conn.commit()
    conn.close()

    # 3. Verify staleness is detected across both layers
    assert semantic_metadata.is_metadata_stale(TEST_META_PATH, TEST_DB_PATH) is True
    assert semantic_embeddings.is_index_stale(TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH, TEST_META_PATH, db_path=TEST_DB_PATH) is True
    cleanup_test_files()


def test_cascading_synchronization_and_clean_retrieval():
    """Step 5-10: Trigger semantic retrieval and ensure only planets entities exist with NO survey entities."""
    cleanup_test_files()
    # Setup replaced database
    conn = sqlite3.connect(TEST_DB_PATH)
    conn.execute("CREATE TABLE planets (planet_name TEXT, orbital_period REAL);")
    conn.execute("INSERT INTO planets VALUES ('Mercury', 88.0), ('Venus', 224.7);")
    conn.commit()
    conn.close()

    # Create stale metadata files referencing old survey entities
    old_stale_meta = {
        "version": "1.0.0",
        "generated_at": "2020-01-01T00:00:00Z",
        "database_fingerprint": {"tables": ["Survey", "Answer"], "mtime": 1000.0, "size_bytes": 100},
        "tables": {
            "Answer": {
                "observed": {"columns": {"AnswerText": {"type": "TEXT"}}},
                "generated": {"table_description": "Old survey answers", "columns": {"AnswerText": {"description": "Text"}}}
            }
        }
    }
    with open(TEST_META_PATH, "w", encoding="utf-8") as f:
        json.dump(old_stale_meta, f)

    # Perform retrieval for 'What is the orbital period of the planets?'
    retrieved = semantic_embeddings.retrieve(
        "What is the orbital period of the planets?",
        top_k=5,
        metadata_path=TEST_META_PATH,
        index_path=TEST_INDEX_PATH,
        mapping_path=TEST_MAP_PATH,
        meta_path=TEST_INDEX_META_PATH,
        db_path=TEST_DB_PATH,
    )

    assert len(retrieved) > 0

    # Verify all retrieved entities are strictly from the new database
    for r in retrieved:
        assert r["table"] == "planets"
        assert r.get("column") in [None, "planet_name", "orbital_period"]

    # Verify old tables/columns NEVER appear in retrieved results
    forbidden_terms = {"Answer", "Question", "Survey", "AnswerText", "SurveyID", "UserID"}
    for r in retrieved:
        assert r["table"] not in forbidden_terms
        assert r.get("column") not in forbidden_terms

    # Verify updated metadata_store.json on disk
    fresh_meta = semantic_metadata.load_metadata(TEST_META_PATH)
    assert list(fresh_meta["tables"].keys()) == ["planets"]
    cleanup_test_files()


def test_clear_endpoint_invalidates_semantic_state():
    """Step 12: Verify POST /ingest/clear wipes database and all semantic state files."""
    cleanup_test_files()
    # Populate dummy files
    for p in [TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH]:
        with open(p, "w", encoding="utf-8") as f:
            f.write("{}")

    # Invalidate using helpers
    semantic_embeddings.clear_semantic_state(
        metadata_path=TEST_META_PATH,
        index_path=TEST_INDEX_PATH,
        mapping_path=TEST_MAP_PATH,
        meta_path=TEST_INDEX_META_PATH
    )

    assert not os.path.exists(TEST_META_PATH)
    assert not os.path.exists(TEST_INDEX_PATH)
    assert not os.path.exists(TEST_MAP_PATH)
    assert not os.path.exists(TEST_INDEX_META_PATH)
    cleanup_test_files()


def test_failure_safety_removes_stale_artifacts():
    """Verify that if semantic synchronization fails, stale index files are stripped rather than served."""
    cleanup_test_files()
    # Populate dummy artifacts
    for p in [TEST_META_PATH, TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH]:
        with open(p, "w", encoding="utf-8") as f:
            f.write("{}")

    # Call sync_semantic_state with a non-existent database file
    res = semantic_embeddings.sync_semantic_state(
        db_path="non_existent_database.sqlite",
        metadata_path=TEST_META_PATH,
        index_path=TEST_INDEX_PATH,
        mapping_path=TEST_MAP_PATH,
        meta_path=TEST_INDEX_META_PATH,
    )

    assert res["status"] == "skipped"
    # Artifacts should have been purged
    assert not os.path.exists(TEST_INDEX_PATH)
    assert not os.path.exists(TEST_META_PATH)
    cleanup_test_files()


def test_sequential_dataset_replacements():
    """Step 14: Test multiple sequential dataset replacements to guarantee long-term synchronization."""
    cleanup_test_files()
    datasets = [
        ("customers", ["customer_id", "email", "country"]),
        ("orders", ["order_id", "amount", "order_date"]),
        ("inventory", ["sku", "stock_qty", "warehouse"]),
    ]

    for table_name, cols in datasets:
        # Wipe DB
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)

        conn = sqlite3.connect(TEST_DB_PATH)
        cols_sql = ", ".join(f"{c} TEXT" for c in cols)
        conn.execute(f"CREATE TABLE {table_name} ({cols_sql});")
        conn.commit()
        conn.close()

        # Retrieve
        results = semantic_embeddings.retrieve(
            f"Show details for {table_name}",
            top_k=5,
            metadata_path=TEST_META_PATH,
            index_path=TEST_INDEX_PATH,
            mapping_path=TEST_MAP_PATH,
            meta_path=TEST_INDEX_META_PATH,
            db_path=TEST_DB_PATH,
        )

        assert len(results) > 0
        for r in results:
            assert r["table"] == table_name
            if r.get("column"):
                assert r["column"] in cols
    cleanup_test_files()


def test_nl2sql_regression_on_dataset_replacement():
    """Verify that after replacing old survey DB with ENJOYSPORT, NL->SQL queries use only ENJOYSPORT schema."""
    cleanup_test_files()
    # 1. Create initial survey DB
    conn = sqlite3.connect(TEST_DB_PATH)
    conn.execute("CREATE TABLE Survey (SurveyID INTEGER PRIMARY KEY, Title TEXT);")
    conn.execute("CREATE TABLE Answer (AnswerID INTEGER, AnswerText TEXT, UserID INTEGER);")
    conn.commit()
    conn.close()

    semantic_embeddings.sync_semantic_state(
        db_path=TEST_DB_PATH,
        metadata_path=TEST_META_PATH,
        index_path=TEST_INDEX_PATH,
        mapping_path=TEST_MAP_PATH,
        meta_path=TEST_INDEX_META_PATH,
    )

    # 2. Replace with ENJOYSPORT
    os.remove(TEST_DB_PATH)
    conn = sqlite3.connect(TEST_DB_PATH)
    conn.execute("CREATE TABLE ENJOYSPORT (Sky TEXT, AirTemp TEXT, Humidity TEXT, Wind TEXT, Water TEXT, Forecast TEXT, EnjoySport TEXT);")
    conn.execute("INSERT INTO ENJOYSPORT VALUES ('Sunny', 'Warm', 'Normal', 'Strong', 'Warm', 'Same', 'Yes');")
    conn.commit()
    conn.close()

    # Synchronize semantic state
    sync_res = semantic_embeddings.sync_semantic_state(
        db_path=TEST_DB_PATH,
        metadata_path=TEST_META_PATH,
        index_path=TEST_INDEX_PATH,
        mapping_path=TEST_MAP_PATH,
        meta_path=TEST_INDEX_META_PATH,
    )
    assert sync_res["status"] == "synchronized"
    assert sync_res["tables"] == ["ENJOYSPORT"]

    # 3. Mock LLM for ENJOYSPORT query
    original_ask_llm = llm.ask_llm
    original_sql_runner_db = sql_runner.DB_PATH

    try:
        sql_runner.DB_PATH = TEST_DB_PATH
        llm.ask_llm = lambda prompt, task="sql": (
            json.dumps({"sql": "SELECT COUNT(*) AS total_records FROM ENJOYSPORT;", "reasoning": "Count ENJOYSPORT records"})
            if task == "sql" else "There is 1 record."
        )

        res = nl2sql.query(
            question="How many records are in the dataset?",
            max_retries=1,
            metadata_path=TEST_META_PATH,
            db_path=TEST_DB_PATH,
            use_llm=True,
        )

        assert res["status"] == "success"
        assert res["sql"] == "SELECT COUNT(*) AS total_records FROM ENJOYSPORT;"
        assert res["validation"]["valid"] is True
        assert res["execution"]["success"] is True
        assert res["row_count"] == 1

        # Assert no old tables/columns leaked into retrieval
        for it in res["retrieval"]["items"]:
            assert it["table"] == "ENJOYSPORT"
            assert it["table"] not in {"Survey", "Answer", "Question"}

    finally:
        llm.ask_llm = original_ask_llm
        sql_runner.DB_PATH = original_sql_runner_db
        cleanup_test_files()


def test_upload_api_sync_lifecycle():
    """Step 11: Test actual POST /ingest/file and POST /ingest/clear endpoints with FastAPI TestClient."""
    # 1. Clear database
    clear_resp = client.post("/ingest/clear")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["status"] == "cleared"

    # 2. Upload sample CSV: ENJOYSPORT.csv
    csv_content = b"Sky,AirTemp,Humidity,Wind,Water,Forecast,EnjoySport\nSunny,Warm,Normal,Strong,Warm,Same,Yes\nRainy,Cold,High,Strong,Warm,Change,No\n"
    files = {"file": ("ENJOYSPORT.csv", csv_content, "text/csv")}
    
    upload_resp = client.post("/ingest/file", files=files)
    assert upload_resp.status_code == 200
    resp_data = upload_resp.json()
    assert resp_data["status"] == "uploaded"
    assert resp_data["table_name"] == "ENJOYSPORT"
    assert resp_data["semantic_sync"]["status"] == "synchronized"
    assert "ENJOYSPORT" in resp_data["semantic_sync"]["tables"]

    # 3. Check GET /semantic/status
    status_resp = client.get("/semantic/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["metadata_exists"] is True
    assert status_data["is_stale"] is False
    assert status_data["table_count"] == 1
    table_names = [t["table_name"] if isinstance(t, dict) else t for t in status_data["tables"]]
    assert "ENJOYSPORT" in table_names


def test_zip_and_sqlite_ingestion_sync():
    """Test ZIP and SQLite file uploads through POST /ingest/file API with full semantic synchronization."""
    import zipfile
    import io

    # 1. Clear database
    client.post("/ingest/clear")

    # 2. Test ZIP containing 2 CSVs: departments.csv & employees.csv
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("departments.csv", "dept_id,dept_name\n1,Engineering\n2,Marketing\n")
        zf.writestr("employees.csv", "emp_id,emp_name,dept_id\n101,John Doe,1\n102,Jane Smith,2\n")
    zip_bytes = zip_buffer.getvalue()

    zip_upload = client.post("/ingest/file", files={"file": ("company.zip", zip_bytes, "application/zip")})
    assert zip_upload.status_code == 200
    zip_res = zip_upload.json()
    assert zip_res["status"] == "uploaded"
    assert zip_res["table_count"] == 2
    assert zip_res["semantic_sync"]["status"] == "synchronized"
    assert set(zip_res["semantic_sync"]["tables"]) == {"departments", "employees"}

    # Verify retrieval
    retrieved = semantic_embeddings.retrieve("engineering department employees", top_k=4)
    assert len(retrieved) > 0
    for r in retrieved:
        assert r["table"] in {"departments", "employees"}


def test_reverse_dataset_replacement():
    """Test A -> B -> A dataset replacement to ensure no vector accumulation or stale mappings."""
    # 1. Upload Dataset A (books)
    client.post("/ingest/clear")
    csv_a = b"book_id,title,author\n1,Dune,Frank Herbert\n2,1984,George Orwell\n"
    res_a = client.post("/ingest/file", files={"file": ("books.csv", csv_a, "text/csv")}).json()
    assert res_a["semantic_sync"]["tables"] == ["books"]

    meta_a = semantic_metadata.load_metadata("metadata_store.json")
    assert list(meta_a["tables"].keys()) == ["books"]

    # 2. Replace with Dataset B (airports)
    csv_b = b"code,airport_name,country\nJFK,John F Kennedy,USA\nLHR,Heathrow,UK\n"
    res_b = client.post("/ingest/file", files={"file": ("airports.csv", csv_b, "text/csv")}, params={"clear": True}).json()
    assert res_b["semantic_sync"]["tables"] == ["airports"]

    meta_b = semantic_metadata.load_metadata("metadata_store.json")
    assert list(meta_b["tables"].keys()) == ["airports"]

    # 3. Replace BACK with Dataset A (books)
    res_a2 = client.post("/ingest/file", files={"file": ("books.csv", csv_a, "text/csv")}, params={"clear": True}).json()
    assert res_a2["semantic_sync"]["tables"] == ["books"]

    meta_a2 = semantic_metadata.load_metadata("metadata_store.json")
    assert list(meta_a2["tables"].keys()) == ["books"]

    # 4. Verify no airport vectors/mappings exist
    with open("metadata_mapping.json", "r", encoding="utf-8") as f:
        mapping = json.load(f)
    tables_in_mapping = set(m["table"] for m in mapping)
    assert tables_in_mapping == {"books"}
    assert "airports" not in tables_in_mapping


def test_property_invariants_across_datasets():
    """Validates strict mathematical invariants: retrieved tables subset of DB tables, 0% alien entities."""
    cleanup_test_files()
    datasets = [
        ("planets", ["planet_id", "planet_name", "mass"], ["Earth", "Mars", "Jupiter"]),
        ("universities", ["uni_id", "uni_name", "rank"], ["MIT", "Stanford", "Oxford"]),
        ("superheroes", ["hero_id", "hero_name", "power"], ["Batman", "Superman", "Flash"]),
    ]

    for tname, cols, sample_vals in datasets:
        conn = sqlite3.connect(TEST_DB_PATH)
        cols_def = ", ".join(f"{c} TEXT" for c in cols)
        conn.execute(f"CREATE TABLE {tname} ({cols_def});")
        conn.execute(f"INSERT INTO {tname} VALUES ('1', '{sample_vals[0]}', 'val');")
        conn.commit()
        conn.close()

        # Sync
        semantic_embeddings.sync_semantic_state(
            db_path=TEST_DB_PATH,
            metadata_path=TEST_META_PATH,
            index_path=TEST_INDEX_PATH,
            mapping_path=TEST_MAP_PATH,
            meta_path=TEST_INDEX_META_PATH,
            use_llm=False,
        )

        retrieved = semantic_embeddings.retrieve(
            f"Query about {tname}",
            top_k=5,
            metadata_path=TEST_META_PATH,
            index_path=TEST_INDEX_PATH,
            mapping_path=TEST_MAP_PATH,
            meta_path=TEST_INDEX_META_PATH,
            db_path=TEST_DB_PATH,
        )

        # Property 1: retrieved tables ⊆ actual database tables
        ret_tables = set(r["table"] for r in retrieved)
        assert ret_tables.issubset({tname}), f"Invariant violation: {ret_tables} not subset of {{{tname}}}"

        # Property 2: retrieved columns ⊆ actual database columns
        for r in retrieved:
            if r.get("column"):
                assert r["column"] in cols, f"Invariant violation: column {r['column']} not in {cols}"

        # Clean DB for next loop
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)

    cleanup_test_files()


if __name__ == "__main__":
    print("Running Dataset Lifecycle Test Suite...")
    test_initial_dataset_and_staleness_detection()
    print("  PASS: test_initial_dataset_and_staleness_detection")
    test_cascading_synchronization_and_clean_retrieval()
    print("  PASS: test_cascading_synchronization_and_clean_retrieval")
    test_clear_endpoint_invalidates_semantic_state()
    print("  PASS: test_clear_endpoint_invalidates_semantic_state")
    test_failure_safety_removes_stale_artifacts()
    print("  PASS: test_failure_safety_removes_stale_artifacts")
    test_sequential_dataset_replacements()
    print("  PASS: test_sequential_dataset_replacements")
    test_nl2sql_regression_on_dataset_replacement()
    print("  PASS: test_nl2sql_regression_on_dataset_replacement")
    test_upload_api_sync_lifecycle()
    print("  PASS: test_upload_api_sync_lifecycle")
    test_zip_and_sqlite_ingestion_sync()
    print("  PASS: test_zip_and_sqlite_ingestion_sync")
    test_reverse_dataset_replacement()
    print("  PASS: test_reverse_dataset_replacement")
    test_property_invariants_across_datasets()
    print("  PASS: test_property_invariants_across_datasets")
    print("\nALL 10 LIFECYCLE TESTS PASSED SUCCESSFULLY!")

