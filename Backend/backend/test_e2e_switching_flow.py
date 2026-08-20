"""
Comprehensive Live E2E Switching & Synchronization Flow Test.
Demonstrates Part 21 Live Sequence: A -> B -> C -> A -> Clear -> Fresh.
"""

import json
import sqlite3
from fastapi.testclient import TestClient

import semantic_metadata
import semantic_embeddings
import llm
from main import app

client = TestClient(app)


def run_e2e_flow():
    print("="*70)
    print("RUNNING LIVE END-TO-END DATASET SWITCHING FLOW (PART 21)")
    print("="*70)

    # 1. Dataset A: books.csv
    print("\n--- 1. Uploading Dataset A: Books ---")
    csv_a = b"book_id,title,author,pages\n1,Dune,Frank Herbert,412\n2,1984,George Orwell,328\n"
    res_a = client.post("/ingest/file", files={"file": ("books.csv", csv_a, "text/csv")}, params={"clear": True}).json()
    assert res_a["status"] == "uploaded"
    assert res_a["semantic_sync"]["status"] == "synchronized"
    assert res_a["semantic_sync"]["tables"] == ["books"]

    # Query Dataset A
    orig_llm = llm.ask_llm
    llm.ask_llm = lambda prompt, task="sql": (
        json.dumps({"sql": "SELECT COUNT(*) AS total_books FROM books;", "reasoning": "Count books"})
        if task == "sql" else "There are books."
    )
    q_a = client.post("/nl2sql/query", json={"question": "How many books are there?"}).json()
    assert q_a["status"] == "success"
    assert q_a["sql"] == "SELECT COUNT(*) AS total_books FROM books;"
    assert q_a["results"] == [{"total_books": 2}]
    print("  Dataset A Query PASS: Books count = 2")

    # 2. Dataset B: airports.csv (Without restarting backend)
    print("\n--- 2. Uploading Dataset B: Airports (Without Restarting Backend) ---")
    csv_b = b"code,airport_name,city,country\nJFK,John F Kennedy,New York,USA\nLHR,Heathrow,London,UK\n"
    res_b = client.post("/ingest/file", files={"file": ("airports.csv", csv_b, "text/csv")}, params={"clear": True}).json()
    assert res_b["status"] == "uploaded"
    assert res_b["semantic_sync"]["status"] == "synchronized"
    assert res_b["semantic_sync"]["tables"] == ["airports"]

    # Verify zero books in metadata or mapping
    meta_b = semantic_metadata.load_metadata("metadata_store.json")
    assert list(meta_b["tables"].keys()) == ["airports"]
    assert "books" not in meta_b["tables"]

    with open("metadata_mapping.json", "r", encoding="utf-8") as f:
        map_b = json.load(f)
    assert set(m["table"] for m in map_b) == {"airports"}

    # Query Dataset B
    llm.ask_llm = lambda prompt, task="sql": (
        json.dumps({"sql": "SELECT COUNT(*) AS total_airports FROM airports;", "reasoning": "Count airports"})
        if task == "sql" else "There are airports."
    )
    q_b = client.post("/nl2sql/query", json={"question": "How many airports are there?"}).json()
    assert q_b["status"] == "success"
    assert q_b["sql"] == "SELECT COUNT(*) AS total_airports FROM airports;"
    assert q_b["results"] == [{"total_airports": 2}]
    # Assert zero Dataset A entities retrieved
    for it in q_b["retrieval"]["items"]:
        assert it["table"] == "airports"
        assert it["table"] != "books"
    print("  Dataset B Query PASS: Airports count = 2, 0% Books leakage")

    # 3. Dataset C: planets.csv (Without restarting backend)
    print("\n--- 3. Uploading Dataset C: Planets (Without Restarting Backend) ---")
    csv_c = b"planet_id,planet_name,orbital_period\n1,Mercury,88.0\n2,Venus,224.7\n3,Earth,365.2\n"
    res_c = client.post("/ingest/file", files={"file": ("planets.csv", csv_c, "text/csv")}, params={"clear": True}).json()
    assert res_c["status"] == "uploaded"
    assert res_c["semantic_sync"]["tables"] == ["planets"]

    # Query Dataset C
    llm.ask_llm = lambda prompt, task="sql": (
        json.dumps({"sql": "SELECT COUNT(*) AS total_planets FROM planets;", "reasoning": "Count planets"})
        if task == "sql" else "There are planets."
    )
    q_c = client.post("/nl2sql/query", json={"question": "How many planets are there?"}).json()
    assert q_c["status"] == "success"
    assert q_c["sql"] == "SELECT COUNT(*) AS total_planets FROM planets;"
    assert q_c["results"] == [{"total_planets": 3}]
    for it in q_c["retrieval"]["items"]:
        assert it["table"] == "planets"
        assert it["table"] not in {"books", "airports"}
    print("  Dataset C Query PASS: Planets count = 3, 0% Books/Airports leakage")

    # 4. Dataset A again (Reverse replacement)
    print("\n--- 4. Uploading Dataset A: Books Again (Reverse Replacement) ---")
    res_a2 = client.post("/ingest/file", files={"file": ("books.csv", csv_a, "text/csv")}, params={"clear": True}).json()
    assert res_a2["semantic_sync"]["tables"] == ["books"]

    meta_a2 = semantic_metadata.load_metadata("metadata_store.json")
    assert list(meta_a2["tables"].keys()) == ["books"]
    assert "planets" not in meta_a2["tables"]
    assert "airports" not in meta_a2["tables"]
    print("  Dataset A Reappeared PASS: 0% Planets/Airports leakage")

    # 5. Clear endpoint
    print("\n--- 5. POST /ingest/clear ---")
    clear_res = client.post("/ingest/clear").json()
    assert clear_res["status"] == "cleared"

    # Status check after clear
    status_after = client.get("/semantic/status").json()
    assert status_after["metadata_exists"] is False
    assert status_after["table_count"] == 0
    print("  Clear PASS: Zero residual artifacts or cached tables")

    # 6. Upload fresh dataset: students.csv
    print("\n--- 6. Upload Fresh Dataset after Clear: Students ---")
    csv_fresh = b"student_id,first_name,gpa\n101,Maya,3.9\n102,Liam,3.8\n"
    res_fresh = client.post("/ingest/file", files={"file": ("students.csv", csv_fresh, "text/csv")}).json()
    assert res_fresh["semantic_sync"]["tables"] == ["students"]

    status_fresh = client.get("/semantic/status").json()
    assert status_fresh["metadata_exists"] is True
    assert status_fresh["table_count"] == 1
    table_names = [t["table_name"] if isinstance(t, dict) else t for t in status_fresh["tables"]]
    assert "students" in table_names
    print("  Fresh Upload PASS: Clean state established with Students table")

    llm.ask_llm = orig_llm
    print("\n" + "="*70)
    print("LIVE E2E SWITCHING & SYNCHRONIZATION TEST PASSED SUCCESSFULLY!")
    print("="*70)


if __name__ == "__main__":
    run_e2e_flow()
