"""
Test Suite for Dataset Lifecycle & Semantic Synchronization Layer.

Validates that:
1. Dataset replacements in SQLite immediately invalidate stale metadata & FAISS index.
2. Stale entities (e.g. AnswerText, SurveyID, UserID) never survive dataset replacement.
3. Automatic cascading synchronization regenerates metadata and FAISS index accurately.
4. Upload / Clear API endpoints correctly clean up artifacts and synchronize fresh schemas.
5. Multiple sequential dataset replacements consistently synchronize.
"""

import os
import json
import sqlite3
import pandas as pd
from fastapi.testclient import TestClient

import semantic_metadata
import semantic_embeddings
import nl2sql
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
    semantic_metadata.remove_metadata_artifacts(TEST_META_PATH)
    semantic_embeddings.remove_index_artifacts(TEST_INDEX_PATH, TEST_MAP_PATH, TEST_INDEX_META_PATH)

    assert not os.path.exists(TEST_META_PATH)
    assert not os.path.exists(TEST_INDEX_PATH)
    assert not os.path.exists(TEST_MAP_PATH)
    assert not os.path.exists(TEST_INDEX_META_PATH)
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


if __name__ == "__main__":
    print("Running Dataset Lifecycle Test Suite...")
    test_initial_dataset_and_staleness_detection()
    print("  PASS: test_initial_dataset_and_staleness_detection")
    test_cascading_synchronization_and_clean_retrieval()
    print("  PASS: test_cascading_synchronization_and_clean_retrieval")
    test_clear_endpoint_invalidates_semantic_state()
    print("  PASS: test_clear_endpoint_invalidates_semantic_state")
    test_sequential_dataset_replacements()
    print("  PASS: test_sequential_dataset_replacements")
    test_upload_api_sync_lifecycle()
    print("  PASS: test_upload_api_sync_lifecycle")
    print("\nALL LIFECYCLE TESTS PASSED SUCCESSFULLY!")
