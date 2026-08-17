"""
Comprehensive test suite for sql_validator module.
Tests valid analytical queries, malicious/mutating SQL rejection, AST safety checks,
unknown tables/columns, comment obfuscation, and the 5 Phase 4 SQL candidates.
"""

import os
import sqlite3
import tempfile
import sql_validator


# Deterministic schema for testing
SAMPLE_SCHEMA = {
    "Survey": {"surveyid", "description"},
    "Question": {"questionid", "questiontext"},
    "Answer": {"answertext", "surveyid", "questionid", "userid"},
}


def test_valid_queries():
    """Verifies all required valid analytical SQLite SQL patterns."""
    # 1. Simple SELECT
    res1 = sql_validator.validate_sql("SELECT COUNT(*) FROM Survey;", active_schema=SAMPLE_SCHEMA)
    assert res1["valid"] is True
    assert res1["read_only"] is True
    assert "Survey" in res1["tables"]

    # 2. SELECT with WHERE
    res2 = sql_validator.validate_sql("SELECT SurveyID, Description FROM Survey WHERE SurveyID > 2014;", active_schema=SAMPLE_SCHEMA)
    assert res2["valid"] is True

    # 3. GROUP BY
    res3 = sql_validator.validate_sql("SELECT SurveyID, COUNT(*) AS cnt FROM Answer GROUP BY SurveyID;", active_schema=SAMPLE_SCHEMA)
    assert res3["valid"] is True

    # 4. ORDER BY + LIMIT
    res4 = sql_validator.validate_sql("SELECT questionid, questiontext FROM Question ORDER BY questionid ASC LIMIT 10;", active_schema=SAMPLE_SCHEMA)
    assert res4["valid"] is True

    # 5. JOIN with Aliases
    res5 = sql_validator.validate_sql(
        "SELECT a.AnswerText, q.questiontext FROM Answer a JOIN Question q ON a.QuestionID = q.questionid;",
        active_schema=SAMPLE_SCHEMA
    )
    assert res5["valid"] is True
    assert set(res5["tables"]) == {"Answer", "Question"}

    # 6. CTE / WITH
    res6 = sql_validator.validate_sql(
        "WITH ActiveSurveys AS (SELECT SurveyID FROM Survey WHERE SurveyID = 2014) SELECT * FROM ActiveSurveys;",
        active_schema=SAMPLE_SCHEMA
    )
    assert res6["valid"] is True
    assert "Survey" in res6["tables"]

    # 7. Subquery
    res7 = sql_validator.validate_sql(
        "SELECT Description FROM Survey WHERE SurveyID IN (SELECT SurveyID FROM Answer);",
        active_schema=SAMPLE_SCHEMA
    )
    assert res7["valid"] is True

    # 8. DISTINCT
    res8 = sql_validator.validate_sql("SELECT DISTINCT UserID FROM Answer;", active_schema=SAMPLE_SCHEMA)
    assert res8["valid"] is True

    # 9. CASE
    res9 = sql_validator.validate_sql(
        "SELECT SurveyID, CASE WHEN SurveyID = 2014 THEN 'old' ELSE 'new' END AS age_tag FROM Survey;",
        active_schema=SAMPLE_SCHEMA
    )
    assert res9["valid"] is True

    # 10. Aggregate functions
    res10 = sql_validator.validate_sql(
        "SELECT COUNT(*), MIN(SurveyID), MAX(SurveyID) FROM Survey;",
        active_schema=SAMPLE_SCHEMA
    )
    assert res10["valid"] is True

    print("  PASS: test_valid_queries (10/10)")


def test_invalid_syntax_and_unparsable():
    """Verifies unparsable or malformed SQL queries fail validation."""
    # 11. Malformed SQL
    res11 = sql_validator.validate_sql("SELECT FROM WHERE;", active_schema=SAMPLE_SCHEMA)
    assert res11["valid"] is False
    assert res11["syntax_valid"] is False
    assert any(e["code"] == "SQL_PARSE_ERROR" for e in res11["errors"])

    # 27. Invalid SQLite syntax (e.g. SQL Server 'SELECT TOP')
    res27 = sql_validator.validate_sql("SELECT TOP 10 * FROM Survey;", active_schema=SAMPLE_SCHEMA)
    assert res27["valid"] is False

    # Empty string
    res_empty = sql_validator.validate_sql("", active_schema=SAMPLE_SCHEMA)
    assert res_empty["valid"] is False

    print("  PASS: test_invalid_syntax_and_unparsable")


def test_unknown_tables_and_columns():
    """Verifies queries referencing non-existent tables or columns are rejected."""
    # 12. Unknown table
    res12 = sql_validator.validate_sql("SELECT * FROM NonExistentTable;", active_schema=SAMPLE_SCHEMA)
    assert res12["valid"] is False
    assert any(e["code"] == "UNKNOWN_TABLE_ERROR" for e in res12["errors"])

    # 13. Unknown column
    res13 = sql_validator.validate_sql("SELECT FakeColumn FROM Survey;", active_schema=SAMPLE_SCHEMA)
    assert res13["valid"] is False
    assert any(e["code"] == "UNKNOWN_COLUMN_ERROR" for e in res13["errors"])

    # Unknown column in qualified join
    res13_join = sql_validator.validate_sql("SELECT s.FakeColumn FROM Survey s;", active_schema=SAMPLE_SCHEMA)
    assert res13_join["valid"] is False
    assert any(e["code"] == "UNKNOWN_COLUMN_ERROR" for e in res13_join["errors"])

    print("  PASS: test_unknown_tables_and_columns")


def test_forbidden_operations_and_mutations():
    """Verifies all mutating and state-altering statements are rejected."""
    # 14. INSERT
    res14 = sql_validator.validate_sql("INSERT INTO Survey (SurveyID) VALUES (9999);", active_schema=SAMPLE_SCHEMA)
    assert res14["valid"] is False
    assert res14["read_only"] is False

    # 15. UPDATE
    res15 = sql_validator.validate_sql("UPDATE Survey SET Description = 'test';", active_schema=SAMPLE_SCHEMA)
    assert res15["valid"] is False
    assert res15["read_only"] is False

    # 16. DELETE
    res16 = sql_validator.validate_sql("DELETE FROM Survey WHERE SurveyID = 2014;", active_schema=SAMPLE_SCHEMA)
    assert res16["valid"] is False
    assert res16["read_only"] is False

    # 17. DROP
    res17 = sql_validator.validate_sql("DROP TABLE Survey;", active_schema=SAMPLE_SCHEMA)
    assert res17["valid"] is False
    assert res17["read_only"] is False

    # 18. ALTER
    res18 = sql_validator.validate_sql("ALTER TABLE Survey ADD COLUMN new_col TEXT;", active_schema=SAMPLE_SCHEMA)
    assert res18["valid"] is False
    assert res18["read_only"] is False

    # 19. CREATE
    res19 = sql_validator.validate_sql("CREATE TABLE Hacked (id INT);", active_schema=SAMPLE_SCHEMA)
    assert res19["valid"] is False
    assert res19["read_only"] is False

    # 20. REPLACE
    res20 = sql_validator.validate_sql("REPLACE INTO Survey (SurveyID) VALUES (1);", active_schema=SAMPLE_SCHEMA)
    assert res20["valid"] is False
    assert res20["read_only"] is False

    # 21. ATTACH
    res21 = sql_validator.validate_sql("ATTACH DATABASE 'evil.db' AS evil;", active_schema=SAMPLE_SCHEMA)
    assert res21["valid"] is False

    # 22. DETACH
    res22 = sql_validator.validate_sql("DETACH DATABASE evil;", active_schema=SAMPLE_SCHEMA)
    assert res22["valid"] is False

    # 23. VACUUM
    res23 = sql_validator.validate_sql("VACUUM;", active_schema=SAMPLE_SCHEMA)
    assert res23["valid"] is False

    # 24. PRAGMA
    res24 = sql_validator.validate_sql("PRAGMA table_info(Survey);", active_schema=SAMPLE_SCHEMA)
    assert res24["valid"] is False

    print("  PASS: test_forbidden_operations_and_mutations (11/11)")


def test_multiple_statements_and_comment_obfuscation():
    """Verifies multiple statements and attempts to hide mutations in comments are blocked."""
    # 25. Multiple statements
    res25 = sql_validator.validate_sql("SELECT COUNT(*) FROM Survey; DROP TABLE Answer;", active_schema=SAMPLE_SCHEMA)
    assert res25["valid"] is False
    assert any(e["code"] == "MULTIPLE_STATEMENTS_ERROR" for e in res25["errors"])

    # 26. Unsafe statement hidden with comments
    res26 = sql_validator.validate_sql("SELECT * FROM Survey; /* comment */ DROP TABLE Answer;", active_schema=SAMPLE_SCHEMA)
    assert res26["valid"] is False
    assert any(e["code"] == "MULTIPLE_STATEMENTS_ERROR" for e in res26["errors"])

    # Valid comment in single statement should pass
    res_valid_comment = sql_validator.validate_sql("SELECT /* harmless comment */ COUNT(*) FROM Survey;", active_schema=SAMPLE_SCHEMA)
    assert res_valid_comment["valid"] is True

    print("  PASS: test_multiple_statements_and_comment_obfuscation")


def test_phase4_generated_candidates():
    """Verifies that all 5 real SQL queries generated in Phase 4 pass validation against live schema."""
    candidates = [
        ("Candidate 1", "SELECT SurveyID, Description FROM Survey;"),
        ("Candidate 2", "SELECT COUNT(*) FROM Answer;"),
        ("Candidate 3", "SELECT Question.questiontext, COUNT(*) AS answer_count FROM Question INNER JOIN Answer ON Question.questionid = Answer.QuestionID GROUP BY Question.questionid ORDER BY answer_count DESC;"),
        ("Candidate 4", "SELECT Survey.SurveyID, COUNT(*) AS answer_count FROM Answer JOIN Survey ON Answer.SurveyID = Survey.SurveyID GROUP BY Survey.SurveyID;"),
        ("Candidate 5", "SELECT s.SurveyID, COUNT(*) AS response_count FROM Answer a JOIN Survey s ON a.SurveyID = s.SurveyID GROUP BY s.SurveyID ORDER BY response_count DESC LIMIT 1;"),
    ]

    for label, sql in candidates:
        res = sql_validator.validate_sql(sql, active_schema=SAMPLE_SCHEMA)
        assert res["valid"] is True, f"{label} failed validation: {res['errors']}"
        assert res["syntax_valid"] is True
        assert res["read_only"] is True
        assert len(res["errors"]) == 0
        print(f"  PASS: {label} -> VALID (tables: {res['tables']})")


if __name__ == "__main__":
    print("\nRunning SQLGlot SQL Validator Test Suite...")
    test_valid_queries()
    test_invalid_syntax_and_unparsable()
    test_unknown_tables_and_columns()
    test_forbidden_operations_and_mutations()
    test_multiple_statements_and_comment_obfuscation()
    print("\nValidating Phase 4 Generated SQL Candidates:")
    test_phase4_generated_candidates()
    print("\nALL VALIDATOR TEST SUITES PASSED SUCCESSFULLY!\n")
