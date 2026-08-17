"""
Comprehensive test suite for nl2sql module and POST /nl2sql/generate endpoint.
Uses mocked LLM responses for deterministic, fast unit tests that DO NOT execute SQL.
"""

import os
import json
import tempfile
from fastapi.testclient import TestClient

import main
import nl2sql
import llm
import semantic_embeddings
import semantic_metadata


def create_sample_metadata():
    """Returns a rich, deterministic metadata dictionary for testing."""
    return {
        "version": "1.0.0",
        "generated_at": "2026-08-17T10:00:00Z",
        "generator": "semantic_metadata.py",
        "model": "qwen3.5:4b",
        "database_file": "test_db.sqlite",
        "database_fingerprint": {
            "mtime": 1786210000.0,
            "size_bytes": 40960,
            "table_count": 3,
            "tables": ["Surveys", "Questions", "Responses"]
        },
        "table_count": 3,
        "tables": {
            "Surveys": {
                "observed": {
                    "table_name": "Surveys",
                    "row_count": 5,
                    "column_count": 3,
                    "columns": {
                        "survey_id": {
                            "name": "survey_id",
                            "type": "INTEGER",
                            "is_pk": True,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 100.0,
                            "sample_values": [2014, 2015, 2016],
                            "top_values": [],
                            "fk_reference": None
                        },
                        "title": {
                            "name": "title",
                            "type": "TEXT",
                            "is_pk": False,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 100.0,
                            "sample_values": ["Annual Dev Survey", "Mental Health in Tech"],
                            "top_values": [],
                            "fk_reference": None
                        },
                        "is_active": {
                            "name": "is_active",
                            "type": "INTEGER",
                            "is_pk": False,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 40.0,
                            "sample_values": [1, 0],
                            "top_values": [],
                            "fk_reference": None
                        }
                    },
                    "relationships": []
                },
                "generated": {
                    "table_description": "Stores master survey definitions and status.",
                    "business_domain": "surveys",
                    "semantic_aliases": ["survey catalog", "forms", "questionnaires"],
                    "columns": {
                        "survey_id": {"description": "Primary key for survey", "semantic_aliases": ["survey id", "year code"], "business_role": "primary_key"},
                        "title": {"description": "Title name of survey", "semantic_aliases": ["survey title", "topic"], "business_role": "dimension"},
                        "is_active": {"description": "Flag indicating if survey is active", "semantic_aliases": ["active status"], "business_role": "status"}
                    },
                    "common_questions": ["How many surveys are there?", "Which surveys are active?"]
                }
            },
            "Questions": {
                "observed": {
                    "table_name": "Questions",
                    "row_count": 100,
                    "column_count": 4,
                    "columns": {
                        "question_id": {
                            "name": "question_id",
                            "type": "INTEGER",
                            "is_pk": True,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 100.0,
                            "sample_values": [1, 2, 3],
                            "top_values": [],
                            "fk_reference": None
                        },
                        "survey_id": {
                            "name": "survey_id",
                            "type": "INTEGER",
                            "is_pk": False,
                            "is_fk": True,
                            "null_percentage": 0.0,
                            "uniqueness": 5.0,
                            "sample_values": [2014, 2015],
                            "top_values": [],
                            "fk_reference": "Surveys.survey_id"
                        },
                        "question_text": {
                            "name": "question_text",
                            "type": "TEXT",
                            "is_pk": False,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 100.0,
                            "sample_values": ["What is your age?", "Do you work remotely?"],
                            "top_values": [],
                            "fk_reference": None
                        },
                        "category": {
                            "name": "category",
                            "type": "TEXT",
                            "is_pk": False,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 10.0,
                            "sample_values": ["demographics", "workplace", "health"],
                            "top_values": [],
                            "fk_reference": None
                        }
                    },
                    "relationships": [
                        {
                            "source_table": "Questions",
                            "source_col": "survey_id",
                            "target_table": "Surveys",
                            "target_col": "survey_id",
                            "type": "foreign_key"
                        }
                    ]
                },
                "generated": {
                    "table_description": "Stores individual question prompts and items in surveys.",
                    "business_domain": "surveys",
                    "semantic_aliases": ["survey items", "inquiries", "prompts"],
                    "columns": {
                        "question_id": {"description": "Unique question ID", "semantic_aliases": ["qid"], "business_role": "primary_key"},
                        "survey_id": {"description": "Parent survey reference", "semantic_aliases": ["survey reference"], "business_role": "foreign_key"},
                        "question_text": {"description": "The exact wording of the question", "semantic_aliases": ["prompt text", "question wording"], "business_role": "text_content"},
                        "category": {"description": "Theme or grouping of question", "semantic_aliases": ["topic", "tag"], "business_role": "dimension"}
                    },
                    "common_questions": ["What questions belong to survey 2014?"]
                }
            },
            "Responses": {
                "observed": {
                    "table_name": "Responses",
                    "row_count": 50000,
                    "column_count": 4,
                    "columns": {
                        "response_id": {
                            "name": "response_id",
                            "type": "INTEGER",
                            "is_pk": True,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 100.0,
                            "sample_values": [1, 2],
                            "top_values": [],
                            "fk_reference": None
                        },
                        "question_id": {
                            "name": "question_id",
                            "type": "INTEGER",
                            "is_pk": False,
                            "is_fk": True,
                            "null_percentage": 0.0,
                            "uniqueness": 0.2,
                            "sample_values": [1, 2],
                            "top_values": [],
                            "fk_reference": "Questions.question_id"
                        },
                        "user_id": {
                            "name": "user_id",
                            "type": "INTEGER",
                            "is_pk": False,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 2.0,
                            "sample_values": [10, 11],
                            "top_values": [],
                            "fk_reference": None
                        },
                        "answer_text": {
                            "name": "answer_text",
                            "type": "TEXT",
                            "is_pk": False,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 10.0,
                            "sample_values": ["Yes", "No", "Maybe"],
                            "top_values": [],
                            "fk_reference": None
                        }
                    },
                    "relationships": [
                        {
                            "source_table": "Responses",
                            "source_col": "question_id",
                            "target_table": "Questions",
                            "target_col": "question_id",
                            "type": "foreign_key"
                        }
                    ]
                },
                "generated": {
                    "table_description": "Stores user feedback and answers to survey questions.",
                    "business_domain": "surveys",
                    "semantic_aliases": ["feedback", "user answers", "survey results"],
                    "columns": {
                        "response_id": {"description": "Unique response ID", "business_role": "primary_key"},
                        "question_id": {"description": "Question answered", "business_role": "foreign_key"},
                        "user_id": {"description": "Respondent ID", "business_role": "identifier"},
                        "answer_text": {"description": "Value of the answer", "semantic_aliases": ["response content"], "business_role": "measure"}
                    },
                    "common_questions": ["How many responses are recorded?"]
                }
            }
        }
    }


def test_sql_context_and_relationship_expansion():
    """Verifies that context builder formats compact schema and expands 1-hop relationships."""
    meta = create_sample_metadata()

    with tempfile.TemporaryDirectory() as tmpdir:
        meta_file = os.path.join(tmpdir, "metadata_store.json")
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        # Retrieval only returned "Responses.question_id"
        retrieved = [
            {"type": "column", "table": "Responses", "column": "question_id", "score": 0.85}
        ]

        context_text, summary = nl2sql.build_sql_context(
            retrieved_items=retrieved,
            metadata_path=meta_file,
            expand_relationships=True
        )

        assert "DATABASE DIALECT: SQLite" in context_text
        assert "Table: `Responses`" in context_text
        # 1-hop expansion should automatically include Questions table
        assert "Table: `Questions`" in context_text
        assert "Questions" in summary["expanded_tables"]
        assert any("Responses.question_id -> Questions.question_id" in r for r in summary["relationships"])

    print("  PASS: test_sql_context_and_relationship_expansion")


def test_prompt_builder():
    """Verifies that build_sql_prompt produces bounded, properly structured prompt."""
    prompt = nl2sql.build_sql_prompt(
        question="How many surveys are there?",
        context_text="Table: `Surveys`\n  Columns:\n    - `survey_id` INTEGER PRIMARY KEY"
    )

    assert "You are a principal database engineer and SQLite Text-to-SQL specialist." in prompt
    assert "USER QUESTION:\nHow many surveys are there?" in prompt
    assert "Table: `Surveys`" in prompt
    assert "CRITICAL INSTRUCTIONS:" in prompt
    assert "SELECT ...;" in prompt

    print("  PASS: test_prompt_builder")


def test_parse_sql_response():
    """Verifies SQL extraction from JSON and plain text fallbacks."""
    # 1. Structured JSON
    json_resp = json.dumps({"sql": "SELECT COUNT(*) FROM Surveys;", "reasoning": "Count rows in Surveys"})
    assert nl2sql.parse_sql_response(json_resp) == "SELECT COUNT(*) FROM Surveys;"

    # 2. Markdown fenced JSON
    md_resp = "```json\n" + json_resp + "\n```"
    assert nl2sql.parse_sql_response(md_resp) == "SELECT COUNT(*) FROM Surveys;"

    # 3. Plain SQL with extra conversational text
    raw_text = "Here is the SQL query:\n```sql\nSELECT title FROM Surveys WHERE is_active = 1;\n```\nHope that helps!"
    assert nl2sql.parse_sql_response(raw_text) == "SELECT title FROM Surveys WHERE is_active = 1;"

    print("  PASS: test_parse_sql_response")


def test_generate_sql_simple_count(monkeypatch):
    """Verifies count query generation flow."""
    mock_sql = "SELECT COUNT(*) FROM Surveys;"
    monkeypatch.setattr(llm, "ask_llm", lambda prompt, task="sql": json.dumps({"sql": mock_sql, "reasoning": "Counts all surveys"}))

    meta = create_sample_metadata()
    with tempfile.TemporaryDirectory() as tmpdir:
        meta_file = os.path.join(tmpdir, "metadata_store.json")
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        
        idx_path = os.path.join(tmpdir, "meta.faiss")
        map_path = os.path.join(tmpdir, "map.json")
        meta_doc_path = os.path.join(tmpdir, "meta_doc.json")
        semantic_embeddings.build_index(meta, idx_path, map_path, meta_doc_path)

        res = nl2sql.generate_sql(
            question="How many surveys are there?",
            metadata_path=meta_file,
            use_llm=True
        )

        assert res["status"] == "success"
        assert res["sql"] == "SELECT COUNT(*) FROM Surveys;"
        assert res["model"] == llm.MODEL_NAME
        assert len(res["retrieval"]["items"]) > 0

    print("  PASS: test_generate_sql_simple_count")


def test_generate_sql_aggregation_and_filtering(monkeypatch):
    """Verifies aggregation and filtering queries."""
    mock_sql = "SELECT category, COUNT(*) as q_count FROM Questions GROUP BY category HAVING COUNT(*) > 5 ORDER BY q_count DESC;"
    monkeypatch.setattr(llm, "ask_llm", lambda prompt, task="sql": json.dumps({"sql": mock_sql}))

    meta = create_sample_metadata()
    with tempfile.TemporaryDirectory() as tmpdir:
        meta_file = os.path.join(tmpdir, "metadata_store.json")
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        res = nl2sql.generate_sql(
            question="Show categories with more than 5 questions sorted by count descending",
            metadata_path=meta_file,
            use_llm=True
        )

        assert res["status"] == "success"
        assert "GROUP BY" in res["sql"]
        assert "ORDER BY" in res["sql"]

    print("  PASS: test_generate_sql_aggregation_and_filtering")


def test_generate_sql_join_query(monkeypatch):
    """Verifies JOIN query generation."""
    mock_sql = "SELECT s.title, q.question_text FROM Surveys s JOIN Questions q ON s.survey_id = q.survey_id WHERE s.is_active = 1;"
    monkeypatch.setattr(llm, "ask_llm", lambda prompt, task="sql": json.dumps({"sql": mock_sql}))

    meta = create_sample_metadata()
    with tempfile.TemporaryDirectory() as tmpdir:
        meta_file = os.path.join(tmpdir, "metadata_store.json")
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        res = nl2sql.generate_sql(
            question="List all active surveys and their questions",
            metadata_path=meta_file,
            use_llm=True
        )

        assert res["status"] == "success"
        assert "JOIN" in res["sql"]

    print("  PASS: test_generate_sql_join_query")


def test_semantic_alias_triggers_retrieval(monkeypatch):
    """Verifies semantic aliases (e.g. 'feedback') correctly retrieve related tables."""
    monkeypatch.setattr(llm, "ask_llm", lambda prompt, task="sql": json.dumps({"sql": "SELECT COUNT(*) FROM Responses;"}))

    meta = create_sample_metadata()
    with tempfile.TemporaryDirectory() as tmpdir:
        meta_file = os.path.join(tmpdir, "metadata_store.json")
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        idx_path = os.path.join(tmpdir, "meta.faiss")
        map_path = os.path.join(tmpdir, "map.json")
        meta_doc_path = os.path.join(tmpdir, "meta_doc.json")
        semantic_embeddings.build_index(meta, idx_path, map_path, meta_doc_path)

        res = nl2sql.generate_sql(
            question="Show total feedback entries received",
            metadata_path=meta_file,
            use_llm=True
        )

        assert res["status"] == "success"
        # 'feedback' is an alias for Responses
        assert "Responses" in res["context"]["tables"]

    print("  PASS: test_semantic_alias_triggers_retrieval")


def test_empty_question_validation():
    """Verifies empty and whitespace questions raise ValueError."""
    try:
        nl2sql.generate_sql("")
        assert False, "Expected ValueError for empty string"
    except ValueError:
        pass

    try:
        nl2sql.generate_sql("   ")
        assert False, "Expected ValueError for whitespace string"
    except ValueError:
        pass

    print("  PASS: test_empty_question_validation")


def test_llm_failure_handling(monkeypatch):
    """Verifies controlled error handling when Ollama fails."""
    monkeypatch.setattr(llm, "ask_llm", lambda prompt, task="sql": (_ for _ in ()).throw(RuntimeError("Connection refused to Ollama")))

    try:
        nl2sql.generate_sql("How many surveys?", use_llm=True)
        assert False, "Expected RuntimeError when LLM fails"
    except RuntimeError as exc:
        assert "LLM generation failed" in str(exc)

    print("  PASS: test_llm_failure_handling")


def test_api_nl2sql_endpoint(monkeypatch):
    """Verifies POST /nl2sql/generate endpoint via TestClient."""
    mock_sql = "SELECT COUNT(*) FROM Survey;"
    monkeypatch.setattr(llm, "ask_llm", lambda prompt, task="sql": json.dumps({"sql": mock_sql, "reasoning": "Count survey table"}))

    client = TestClient(main.app)

    # 1. Success request
    resp = client.post("/nl2sql/generate", json={"question": "How many surveys are there?", "top_k": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["sql"] == mock_sql
    assert "retrieval" in data
    assert "context" in data

    # 2. Empty question -> 400 Bad Request
    resp_bad = client.post("/nl2sql/generate", json={"question": "   "})
    assert resp_bad.status_code == 400

    print("  PASS: test_api_nl2sql_endpoint")


if __name__ == "__main__":
    print("\nRunning NL-to-SQL Generation Test Suite...")
    test_sql_context_and_relationship_expansion()
    test_prompt_builder()
    test_parse_sql_response()
    
    # Run mock tests
    class MockMonkeypatch:
        def setattr(self, target, name, value):
            setattr(target, name, value)

    mp = MockMonkeypatch()
    test_generate_sql_simple_count(mp)
    test_generate_sql_aggregation_and_filtering(mp)
    test_generate_sql_join_query(mp)
    test_semantic_alias_triggers_retrieval(mp)
    test_empty_question_validation()
    test_llm_failure_handling(mp)
    test_api_nl2sql_endpoint(mp)

    print("\nALL 10 TEST SUITES PASSED SUCCESSFULLY!\n")
