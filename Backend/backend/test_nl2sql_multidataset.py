"""
Comprehensive Multi-Dataset Functional Evaluation Suite for SchemaSense NL-to-SQL Pipeline.

Evaluates 4 independent schemas:
1. E-Commerce (customers, products, orders)
2. Employee / HR (departments, employees, salaries)
3. Movies (movies, actors, ratings)
4. Weather (stations, weather_readings)

Evaluates:
- Semantic Synchronization & Database Fingerprinting
- FAISS Retrieval Precision & Score Distributions
- Schema Isolation across Sequential Replacements
- SQLGlot AST Validation & Safety Layer
- Read-Only SQLite Execution Accuracy
- Ground Truth Result Verification (Aggregation, Filter, Group By, Multi-Table Joins)
- Bounded Self-Correction on Complex / Fault-Injected Queries
"""

import os
import re
import json
import time
import sqlite3
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple

import schema
import quality
import analysis
import semantic_metadata
import semantic_embeddings
import sql_validator
import sql_runner
import nl2sql
import llm

TEST_DB_PATH = "test_multidataset_db.sqlite"
TEST_META_PATH = "test_multidataset_meta.json"
TEST_INDEX_PATH = "test_multidataset_index.faiss"
TEST_MAP_PATH = "test_multidataset_mapping.json"
TEST_INDEX_META_PATH = "test_multidataset_idx_meta.json"

ORIGINAL_DB_PATHS = {
    "schema": schema.DB_PATH,
    "quality": quality.DB_PATH,
    "analysis": analysis.DB_PATH,
    "sql_runner": sql_runner.DB_PATH,
}


def bind_test_db():
    """Binds all backend modules to the temporary test SQLite database."""
    schema.DB_PATH = TEST_DB_PATH
    quality.DB_PATH = TEST_DB_PATH
    analysis.DB_PATH = TEST_DB_PATH
    sql_runner.DB_PATH = TEST_DB_PATH


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


# ==============================================================================
# DATASET CREATION HELPERS
# ==============================================================================

def create_ecommerce_db():
    """Dataset 1: E-Commerce (customers, products, orders)."""
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
        (1001, 1, 10, 2, '2026-01-15'),  # 2 * 25 = 50
        (1002, 1, 20, 1, '2026-01-16'),  # 1 * 100 = 100
        (1003, 2, 30, 4, '2026-01-17'),  # 4 * 15 = 60
        (1004, 3, 20, 2, '2026-01-18'),  # 2 * 100 = 200
        (1005, 4, 40, 1, '2026-01-19'),  # 1 * 45 = 45
    ])
    conn.commit()
    conn.close()


def create_hr_db():
    """Dataset 2: Employee / HR (departments, employees, salaries)."""
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


def create_movies_db():
    """Dataset 3: Movies (movies, actors, ratings)."""
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


def create_weather_db():
    """Dataset 4: Weather (stations, weather_readings)."""
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
# SCHEMA-AWARE DETERMINISTIC LLM MOCK FOR EVALUATION
# ==============================================================================

def make_eval_mock_llm(dataset_id: str):
    """Returns a deterministic, schema-grounded LLM mock for the evaluation questions."""
    def mock_ask_llm(prompt: str, task: str = "sql") -> str:
        if task == "interpret":
            return "Evaluation Explanation: Query executed successfully and answered the natural-language question."

        q_match = re.search(r"QUESTION:\s*(.*?)(?:\n|$)", prompt, re.IGNORECASE)
        q_text = q_match.group(1).lower().strip() if q_match else prompt.lower()

        # ----------------------------------------------------------------------
        # DATASET 1: E-COMMERCE
        # ----------------------------------------------------------------------
        if dataset_id == "ecommerce":
            if "catalog" in q_text or "total products" in q_text:
                return json.dumps({
                    "sql": "SELECT COUNT(*) AS total_products FROM products;",
                    "reasoning": "Count total rows in products catalog."
                })
            elif "seattle" in q_text:
                return json.dumps({
                    "sql": "SELECT COUNT(*) AS seattle_customers FROM customers WHERE city = 'Seattle';",
                    "reasoning": "Count customers with city equal to Seattle."
                })
            elif "per category" in q_text or "quantity of products ordered per category" in q_text:
                return json.dumps({
                    "sql": "SELECT p.category, SUM(o.quantity) AS total_qty FROM orders o JOIN products p ON o.product_id = p.product_id GROUP BY p.category ORDER BY p.category;",
                    "reasoning": "Join orders and products, group by category, sum quantity."
                })
            elif "alice smith" in q_text or "total spend" in q_text:
                return json.dumps({
                    "sql": "SELECT c.customer_name, SUM(o.quantity * p.unit_price) AS total_spend FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN products p ON o.product_id = p.product_id WHERE c.customer_name = 'Alice Smith' GROUP BY c.customer_name;",
                    "reasoning": "Join customers, orders, and products to calculate total spend for Alice Smith."
                })

        # ----------------------------------------------------------------------
        # DATASET 2: HR
        # ----------------------------------------------------------------------
        elif dataset_id == "hr":
            if "average employee salary" in q_text or "avg salary" in q_text:
                return json.dumps({
                    "sql": "SELECT AVG(amount) AS avg_salary FROM salaries WHERE effective_year = 2026;",
                    "reasoning": "Compute average salary amount for year 2026."
                })
            elif "after 2022-01-01" in q_text or "hired after" in q_text:
                return json.dumps({
                    "sql": "SELECT full_name FROM employees WHERE hire_date > '2022-01-01' ORDER BY full_name;",
                    "reasoning": "Filter employees hired after 2022-01-01."
                })
            elif "in each department" in q_text or "employees are in each department" in q_text:
                return json.dumps({
                    "sql": "SELECT d.department_name, COUNT(e.employee_id) AS emp_count FROM departments d JOIN employees e ON d.department_id = e.department_id GROUP BY d.department_name ORDER BY d.department_name;",
                    "reasoning": "Join departments and employees, group by department name, count employees."
                })
            elif "highest total salary" in q_text or "payroll" in q_text:
                return json.dumps({
                    "sql": "SELECT d.department_name, SUM(s.amount) AS total_payroll FROM departments d JOIN employees e ON d.department_id = e.department_id JOIN salaries s ON e.employee_id = s.employee_id GROUP BY d.department_name ORDER BY total_payroll DESC LIMIT 1;",
                    "reasoning": "Join departments, employees, and salaries to find department with highest payroll."
                })

        # ----------------------------------------------------------------------
        # DATASET 3: MOVIES
        # ----------------------------------------------------------------------
        elif dataset_id == "movies":
            if "total movie ratings" in q_text or "ratings have been recorded" in q_text:
                return json.dumps({
                    "sql": "SELECT COUNT(*) AS total_ratings FROM ratings;",
                    "reasoning": "Count total records in ratings table."
                })
            elif "year 2014" in q_text or "released in the year 2014" in q_text:
                return json.dumps({
                    "sql": "SELECT COUNT(*) AS count_2014 FROM movies WHERE release_year = 2014;",
                    "reasoning": "Count movies where release_year is 2014."
                })
            elif "rating score for each genre" in q_text or "for each genre" in q_text:
                return json.dumps({
                    "sql": "SELECT m.genre, AVG(r.rating_score) AS avg_score FROM movies m JOIN ratings r ON m.movie_id = r.movie_id GROUP BY m.genre ORDER BY m.genre;",
                    "reasoning": "Join movies and ratings, group by genre, calculate average score."
                })
            elif "highest average rating score" in q_text or "highest average rating" in q_text:
                return json.dumps({
                    "sql": "SELECT m.title, AVG(r.rating_score) AS avg_score FROM movies m JOIN ratings r ON m.movie_id = r.movie_id GROUP BY m.title ORDER BY avg_score DESC LIMIT 1;",
                    "reasoning": "Join movies and ratings, group by title, order by avg rating desc limit 1."
                })

        # ----------------------------------------------------------------------
        # DATASET 4: WEATHER
        # ----------------------------------------------------------------------
        elif dataset_id == "weather":
            if "maximum temperature" in q_text:
                return json.dumps({
                    "sql": "SELECT MAX(temperature_c) AS max_temp FROM weather_readings;",
                    "reasoning": "Compute maximum temperature from weather_readings."
                })
            elif "greater than 10" in q_text or "precipitation greater than" in q_text:
                return json.dumps({
                    "sql": "SELECT COUNT(*) AS heavy_rain_count FROM weather_readings WHERE precipitation_mm > 10.0;",
                    "reasoning": "Count readings where precipitation is greater than 10 mm."
                })
            elif "average humidity percentage for each weather station" in q_text or "humidity" in q_text:
                return json.dumps({
                    "sql": "SELECT s.station_name, AVG(w.humidity_pct) AS avg_humidity FROM stations s JOIN weather_readings w ON s.station_id = w.station_id GROUP BY s.station_name ORDER BY s.station_name;",
                    "reasoning": "Join stations and weather_readings, group by station_name, avg humidity."
                })
            elif "highest total precipitation" in q_text:
                return json.dumps({
                    "sql": "SELECT s.station_name, SUM(w.precipitation_mm) AS total_precip FROM stations s JOIN weather_readings w ON s.station_id = w.station_id GROUP BY s.station_name ORDER BY total_precip DESC LIMIT 1;",
                    "reasoning": "Join stations and weather readings, group by station, sum precipitation desc limit 1."
                })

        return json.dumps({"sql": "SELECT 1;", "reasoning": "Fallback query."})

    return mock_ask_llm


# ==============================================================================
# PIPELINE EVALUATION HARNESS
# ==============================================================================

def evaluate_query(
    question: str,
    dataset_id: str,
    expected_tables: set,
    forbidden_tables: set,
    expected_result_validator: callable,
    mock_llm_fn: callable,
) -> Dict[str, Any]:
    """Evaluates a single question through the full NL-to-SQL pipeline and asserts strict ground truth."""
    bind_test_db()
    original_ask_llm = llm.ask_llm
    llm.ask_llm = mock_llm_fn

    start_t = time.time()
    try:
        res = nl2sql.query(
            question=question,
            max_retries=2,
            top_k=8,
            metadata_path=TEST_META_PATH,
            db_path=TEST_DB_PATH,
            use_llm=True,
        )
    finally:
        llm.ask_llm = original_ask_llm

    latency_ms = int((time.time() - start_t) * 1000)

    # 1. Pipeline status
    assert res["status"] == "success", f"Pipeline failed on '{question}': {res.get('error')}"
    sql_text = res["sql"]
    assert sql_text is not None and len(sql_text) > 0

    # 2. Validation & Read-Only Check
    assert res["validation"]["valid"] is True, f"Validation failed for SQL '{sql_text}': {res['validation'].get('errors')}"
    assert res["execution"]["success"] is True, f"Execution failed for SQL '{sql_text}': {res['execution'].get('error')}"

    # 3. Retrieval Precision & Schema Isolation
    retrieved_items = res["retrieval"]["items"]
    assert len(retrieved_items) > 0, "Zero semantic items retrieved."
    retrieved_tables = []
    retrieved_columns = []
    retrieval_scores = []

    for item in retrieved_items:
        tname = item.get("table")
        cname = item.get("column")
        score = item.get("score")
        retrieved_tables.append(tname)
        if cname:
            retrieved_columns.append(cname)
        retrieval_scores.append(score)

        # STRICT ISOLATION ASSERTION
        assert tname in expected_tables, f"Alien/Stale table '{tname}' retrieved in dataset '{dataset_id}'! Allowed: {expected_tables}"
        assert tname not in forbidden_tables, f"Forbidden table '{tname}' leaked into dataset '{dataset_id}'!"

    # 4. Generated SQL Schema Isolation (Zero Hallucinated / Alien Tables)
    for forbidden in forbidden_tables:
        pattern = rf"\b{re.escape(forbidden)}\b"
        assert not re.search(pattern, sql_text, re.IGNORECASE), f"Forbidden entity '{forbidden}' referenced in SQL: {sql_text}"

    # 5. Ground Truth Result Verification
    actual_rows = res["results"]
    is_correct = expected_result_validator(actual_rows)
    assert is_correct is True, f"Execution result did not match ground truth! Actual rows: {actual_rows}"

    return {
        "question": question,
        "retrieved_tables": list(set(retrieved_tables)),
        "retrieved_columns": list(set(retrieved_columns)),
        "retrieval_scores": retrieval_scores[:4],
        "sql": sql_text,
        "valid": res["validation"]["valid"],
        "executed": res["execution"]["success"],
        "retry_count": res["retry_count"],
        "final_status": res["status"],
        "actual_rows": actual_rows,
        "latency_ms": latency_ms,
    }


# ==============================================================================
# DATASET EVALUATION SUITES
# ==============================================================================

def run_ecommerce_eval() -> List[Dict[str, Any]]:
    """Evaluates 4 core questions + ground truth on Dataset 1 (E-Commerce)."""
    print("\n" + "="*70)
    print("DATASET 1 EVALUATION: E-COMMERCE (customers, products, orders)")
    print("="*70)
    create_ecommerce_db()

    # Synchronize semantic state
    sync_res = semantic_embeddings.sync_semantic_state(
        db_path=TEST_DB_PATH,
        metadata_path=TEST_META_PATH,
        index_path=TEST_INDEX_PATH,
        mapping_path=TEST_MAP_PATH,
        meta_path=TEST_INDEX_META_PATH,
        use_llm=False
    )
    assert sync_res["status"] == "synchronized"
    assert set(sync_res["tables"]) == {"customers", "products", "orders"}

    allowed = {"customers", "products", "orders"}
    forbidden = {"employees", "departments", "salaries", "movies", "actors", "ratings", "stations", "weather_readings", "Survey", "Answer", "Question"}
    mock_llm = make_eval_mock_llm("ecommerce")

    results = []

    # Q1: Simple Aggregation
    r1 = evaluate_query(
        question="How many total products are in the catalog?",
        dataset_id="ecommerce",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=lambda rows: len(rows) == 1 and rows[0].get("total_products") == 4,
        mock_llm_fn=mock_llm,
    )
    results.append(r1)

    # Q2: Filtering
    r2 = evaluate_query(
        question="How many customers are located in Seattle?",
        dataset_id="ecommerce",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=lambda rows: len(rows) == 1 and rows[0].get("seattle_customers") == 2,
        mock_llm_fn=mock_llm,
    )
    results.append(r2)

    # Q3: GROUP BY
    def validate_category_qty(rows):
        cat_map = {row["category"]: row["total_qty"] for row in rows}
        return cat_map == {"Electronics": 5, "Kitchen": 4, "Furniture": 1}

    r3 = evaluate_query(
        question="What is the total quantity of products ordered per category?",
        dataset_id="ecommerce",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=validate_category_qty,
        mock_llm_fn=mock_llm,
    )
    results.append(r3)

    # Q4: Multi-Table JOIN (customers + orders + products)
    r4 = evaluate_query(
        question="What is the total spend for customer Alice Smith?",
        dataset_id="ecommerce",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=lambda rows: len(rows) == 1 and rows[0]["customer_name"] == "Alice Smith" and rows[0]["total_spend"] == 150.0,
        mock_llm_fn=mock_llm,
    )
    results.append(r4)

    for r in results:
        print(f"  [PASS] '{r['question']}' -> SQL: {r['sql']} (Rows: {r['actual_rows']})")

    return results


def run_hr_eval() -> List[Dict[str, Any]]:
    """Evaluates 4 core questions + ground truth on Dataset 2 (Employee / HR)."""
    print("\n" + "="*70)
    print("DATASET 2 EVALUATION: EMPLOYEE / HR (departments, employees, salaries)")
    print("="*70)
    create_hr_db()

    sync_res = semantic_embeddings.sync_semantic_state(
        db_path=TEST_DB_PATH,
        metadata_path=TEST_META_PATH,
        index_path=TEST_INDEX_PATH,
        mapping_path=TEST_MAP_PATH,
        meta_path=TEST_INDEX_META_PATH,
        use_llm=False
    )
    assert sync_res["status"] == "synchronized"
    assert set(sync_res["tables"]) == {"departments", "employees", "salaries"}

    allowed = {"departments", "employees", "salaries"}
    forbidden = {"customers", "products", "orders", "movies", "actors", "ratings", "stations", "weather_readings", "Survey", "Answer", "Question"}
    mock_llm = make_eval_mock_llm("hr")

    results = []

    # Q1: Simple Aggregation
    r1 = evaluate_query(
        question="What is the average employee salary?",
        dataset_id="hr",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=lambda rows: len(rows) == 1 and abs(rows[0]["avg_salary"] - 107000.0) < 0.01,
        mock_llm_fn=mock_llm,
    )
    results.append(r1)

    # Q2: Filtering
    r2 = evaluate_query(
        question="List employees hired after 2022-01-01",
        dataset_id="hr",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=lambda rows: [r["full_name"] for r in rows] == ["John Doe", "Mark White", "Sam Green"],
        mock_llm_fn=mock_llm,
    )
    results.append(r2)

    # Q3: GROUP BY
    def validate_dept_emp_count(rows):
        m = {r["department_name"]: r["emp_count"] for r in rows}
        return m == {"Engineering": 3, "Finance": 1, "Human Resources": 1}

    r3 = evaluate_query(
        question="How many employees are in each department?",
        dataset_id="hr",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=validate_dept_emp_count,
        mock_llm_fn=mock_llm,
    )
    results.append(r3)

    # Q4: Multi-Table JOIN (departments + employees + salaries)
    r4 = evaluate_query(
        question="Which department has the highest total salary expenditure?",
        dataset_id="hr",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=lambda rows: len(rows) == 1 and rows[0]["department_name"] == "Engineering" and rows[0]["total_payroll"] == 365000.0,
        mock_llm_fn=mock_llm,
    )
    results.append(r4)

    for r in results:
        print(f"  [PASS] '{r['question']}' -> SQL: {r['sql']} (Rows: {r['actual_rows']})")

    return results


def run_movies_eval() -> List[Dict[str, Any]]:
    """Evaluates 4 core questions + ground truth on Dataset 3 (Movies)."""
    print("\n" + "="*70)
    print("DATASET 3 EVALUATION: MOVIES (movies, actors, ratings)")
    print("="*70)
    create_movies_db()

    sync_res = semantic_embeddings.sync_semantic_state(
        db_path=TEST_DB_PATH,
        metadata_path=TEST_META_PATH,
        index_path=TEST_INDEX_PATH,
        mapping_path=TEST_MAP_PATH,
        meta_path=TEST_INDEX_META_PATH,
        use_llm=False
    )
    assert sync_res["status"] == "synchronized"
    assert set(sync_res["tables"]) == {"movies", "actors", "ratings"}

    allowed = {"movies", "actors", "ratings"}
    forbidden = {"customers", "products", "orders", "departments", "employees", "salaries", "stations", "weather_readings", "Survey", "Answer", "Question"}
    mock_llm = make_eval_mock_llm("movies")

    results = []

    # Q1: Simple Aggregation
    r1 = evaluate_query(
        question="How many total movie ratings have been recorded?",
        dataset_id="movies",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=lambda rows: len(rows) == 1 and rows[0]["total_ratings"] == 7,
        mock_llm_fn=mock_llm,
    )
    results.append(r1)

    # Q2: Filtering
    r2 = evaluate_query(
        question="How many movies were released in the year 2014?",
        dataset_id="movies",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=lambda rows: len(rows) == 1 and rows[0]["count_2014"] == 2,
        mock_llm_fn=mock_llm,
    )
    results.append(r2)

    # Q3: GROUP BY
    def validate_genre_ratings(rows):
        m = {r["genre"]: round(r["avg_score"], 2) for r in rows}
        return m == {"Action": 9.25, "Drama": 8.5, "Sci-Fi": 8.8}

    r3 = evaluate_query(
        question="What is the average rating score for each genre?",
        dataset_id="movies",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=validate_genre_ratings,
        mock_llm_fn=mock_llm,
    )
    results.append(r3)

    # Q4: Multi-Table JOIN (movies + ratings)
    r4 = evaluate_query(
        question="Which movie has the highest average rating score?",
        dataset_id="movies",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=lambda rows: len(rows) == 1 and rows[0]["title"] == "The Dark Knight" and rows[0]["avg_score"] == 9.25,
        mock_llm_fn=mock_llm,
    )
    results.append(r4)

    for r in results:
        print(f"  [PASS] '{r['question']}' -> SQL: {r['sql']} (Rows: {r['actual_rows']})")

    return results


def run_weather_eval() -> List[Dict[str, Any]]:
    """Evaluates 4 core questions + ground truth on Dataset 4 (Weather)."""
    print("\n" + "="*70)
    print("DATASET 4 EVALUATION: WEATHER (stations, weather_readings)")
    print("="*70)
    create_weather_db()

    sync_res = semantic_embeddings.sync_semantic_state(
        db_path=TEST_DB_PATH,
        metadata_path=TEST_META_PATH,
        index_path=TEST_INDEX_PATH,
        mapping_path=TEST_MAP_PATH,
        meta_path=TEST_INDEX_META_PATH,
        use_llm=False
    )
    assert sync_res["status"] == "synchronized"
    assert set(sync_res["tables"]) == {"stations", "weather_readings"}

    allowed = {"stations", "weather_readings"}
    forbidden = {"customers", "products", "orders", "departments", "employees", "salaries", "movies", "actors", "ratings", "Survey", "Answer", "Question"}
    mock_llm = make_eval_mock_llm("weather")

    results = []

    # Q1: Simple Aggregation
    r1 = evaluate_query(
        question="What is the maximum temperature recorded across all stations?",
        dataset_id="weather",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=lambda rows: len(rows) == 1 and rows[0]["max_temp"] == 31.0,
        mock_llm_fn=mock_llm,
    )
    results.append(r1)

    # Q2: Filtering
    r2 = evaluate_query(
        question="How many weather readings had precipitation greater than 10 mm?",
        dataset_id="weather",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=lambda rows: len(rows) == 1 and rows[0]["heavy_rain_count"] == 2,
        mock_llm_fn=mock_llm,
    )
    results.append(r2)

    # Q3: GROUP BY
    def validate_station_humidity(rows):
        m = {r["station_name"]: round(r["avg_humidity"], 1) for r in rows}
        return m == {"Central Park NY": 67.5, "LAX Airport": 52.5, "O'Hare Chicago": 70.0}

    r3 = evaluate_query(
        question="What is the average humidity percentage for each weather station?",
        dataset_id="weather",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=validate_station_humidity,
        mock_llm_fn=mock_llm,
    )
    results.append(r3)

    # Q4: Multi-Table JOIN (stations + weather_readings)
    r4 = evaluate_query(
        question="Which station recorded the highest total precipitation?",
        dataset_id="weather",
        expected_tables=allowed,
        forbidden_tables=forbidden,
        expected_result_validator=lambda rows: len(rows) == 1 and rows[0]["station_name"] == "O'Hare Chicago" and rows[0]["total_precip"] == 25.0,
        mock_llm_fn=mock_llm,
    )
    results.append(r4)

    for r in results:
        print(f"  [PASS] '{r['question']}' -> SQL: {r['sql']} (Rows: {r['actual_rows']})")

    return results


def run_bounded_self_correction_eval() -> Dict[str, Any]:
    """Tests bounded self-correction when Qwen generates an invalid initial query candidate."""
    print("\n" + "="*70)
    print("SELF-CORRECTION EVALUATION: Complex Multi-Join with Fault Injection")
    print("="*70)
    create_ecommerce_db()

    sync_res = semantic_embeddings.sync_semantic_state(
        db_path=TEST_DB_PATH,
        metadata_path=TEST_META_PATH,
        index_path=TEST_INDEX_PATH,
        mapping_path=TEST_MAP_PATH,
        meta_path=TEST_INDEX_META_PATH,
        use_llm=False
    )
    assert sync_res["status"] == "synchronized"

    bind_test_db()
    attempt_tracker = {"attempt": 0}

    def faulty_mock_llm(prompt: str, task: str = "sql") -> str:
        attempt_tracker["attempt"] += 1
        if task == "interpret":
            return "Self-correction succeeded."

        if attempt_tracker["attempt"] == 1:
            # Attempt 0: Fault injection - hallucinated table 'clients' and syntax error
            return json.dumps({
                "sql": "SELECT customer_name, COUNT(order_id) FROM clients WHERE;",
                "reasoning": "Erroneous SQL with invalid syntax and non-existent table"
            })
        else:
            # Attempt 1: Corrected SQL with proper tables and join
            return json.dumps({
                "sql": "SELECT c.customer_name, COUNT(o.order_id) AS order_count FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_name ORDER BY c.customer_name;",
                "reasoning": "Corrected query using customers and orders tables."
            })

    original_ask_llm = llm.ask_llm
    llm.ask_llm = faulty_mock_llm

    try:
        res = nl2sql.query(
            question="Show the customer names and their order count",
            max_retries=2,
            metadata_path=TEST_META_PATH,
            db_path=TEST_DB_PATH,
            use_llm=True,
        )
    finally:
        llm.ask_llm = original_ask_llm

    assert res["status"] == "success"
    assert res["retry_count"] == 1
    assert len(res["attempts"]) == 2
    assert res["attempts"][0]["validation"]["valid"] is False
    assert res["attempts"][0]["execution"] is None
    assert res["attempts"][1]["validation"]["valid"] is True
    assert res["attempts"][1]["execution"]["success"] is True

    actual_rows = res["results"]
    expected_order_counts = [
        {"customer_name": "Alice Smith", "order_count": 2},
        {"customer_name": "Bob Jones", "order_count": 1},
        {"customer_name": "Charlie Brown", "order_count": 1},
        {"customer_name": "Diana Prince", "order_count": 1},
    ]
    assert actual_rows == expected_order_counts, f"Self-corrected rows mismatch: {actual_rows}"

    print(f"  [PASS] Self-Correction Repaired Query (Retries: {res['retry_count']})")
    print(f"         Attempt 0 Rejected: {res['attempts'][0]['sql']}")
    print(f"         Attempt 1 Validated & Executed: {res['attempts'][1]['sql']}")
    print(f"         Rows: {actual_rows}")

    return {
        "question": "Show the customer names and their order count",
        "retry_count": res["retry_count"],
        "repaired": True,
        "results": actual_rows
    }


if __name__ == "__main__":
    print("\n" + "#"*70)
    print("# STARTING MULTI-DATASET FUNCTIONAL EVALUATION (4 DISTINCT SCHEMAS)")
    print("#"*70)

    try:
        ecom_results = run_ecommerce_eval()
        hr_results = run_hr_eval()
        movies_results = run_movies_eval()
        weather_results = run_weather_eval()
        correction_result = run_bounded_self_correction_eval()

        total_queries = len(ecom_results) + len(hr_results) + len(movies_results) + len(weather_results) + 1
        print("\n" + "#"*70)
        print(f"# COMPLETED EVALUATION: {total_queries}/{total_queries} QUERIES PASSED WITH 100% GROUND TRUTH ACCURACY")
        print("#"*70)

    finally:
        cleanup_all_artifacts()
