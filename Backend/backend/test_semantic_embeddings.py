"""
Comprehensive test suite for semantic_embeddings and FAISS retrieval.
Can be run directly via python test_semantic_embeddings.py or via pytest.
"""

import os
import json
import tempfile
import numpy as np
import faiss

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
            "table_count": 2,
            "tables": ["Customers", "Orders"]
        },
        "table_count": 2,
        "tables": {
            "Customers": {
                "observed": {
                    "table_name": "Customers",
                    "row_count": 100,
                    "column_count": 3,
                    "columns": {
                        "customer_id": {
                            "name": "customer_id",
                            "type": "INTEGER",
                            "is_pk": True,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 100.0,
                            "sample_values": [1, 2, 3],
                            "top_values": [{"value": 1, "count": 1}],
                            "fk_reference": None
                        },
                        "name": {
                            "name": "name",
                            "type": "TEXT",
                            "is_pk": False,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 95.0,
                            "sample_values": ["Alice", "Bob"],
                            "top_values": [],
                            "fk_reference": None
                        },
                        "city": {
                            "name": "city",
                            "type": "TEXT",
                            "is_pk": False,
                            "is_fk": False,
                            "null_percentage": 5.0,
                            "uniqueness": 12.0,
                            "sample_values": ["New York", "London"],
                            "top_values": [{"value": "New York", "count": 20}],
                            "fk_reference": None
                        }
                    },
                    "relationships": []
                },
                "generated": {
                    "table_description": "Stores customer profiles and demographic location information.",
                    "business_domain": "customer_relationship_management",
                    "semantic_aliases": ["clients", "buyers", "accounts"],
                    "columns": {
                        "customer_id": {
                            "description": "Unique identifier for each customer.",
                            "semantic_aliases": ["account number", "client id"],
                            "business_role": "primary_key"
                        },
                        "name": {
                            "description": "Full name of the registered customer.",
                            "semantic_aliases": ["client name", "customer name"],
                            "business_role": "dimension"
                        },
                        "city": {
                            "description": "City where the customer resides.",
                            "semantic_aliases": ["location", "metro"],
                            "business_role": "dimension"
                        }
                    },
                    "common_questions": ["How many customers are in New York?", "List all customer names."]
                }
            },
            "Orders": {
                "observed": {
                    "table_name": "Orders",
                    "row_count": 500,
                    "column_count": 3,
                    "columns": {
                        "order_id": {
                            "name": "order_id",
                            "type": "INTEGER",
                            "is_pk": True,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 100.0,
                            "sample_values": [101, 102],
                            "top_values": [],
                            "fk_reference": None
                        },
                        "customer_id": {
                            "name": "customer_id",
                            "type": "INTEGER",
                            "is_pk": False,
                            "is_fk": True,
                            "null_percentage": 0.0,
                            "uniqueness": 20.0,
                            "sample_values": [1, 2],
                            "top_values": [],
                            "fk_reference": "Customers.customer_id"
                        },
                        "total_amount": {
                            "name": "total_amount",
                            "type": "REAL",
                            "is_pk": False,
                            "is_fk": False,
                            "null_percentage": 0.0,
                            "uniqueness": 80.0,
                            "sample_values": [99.50, 249.99],
                            "top_values": [],
                            "fk_reference": None
                        }
                    },
                    "relationships": [
                        {
                            "source_table": "Orders",
                            "source_col": "customer_id",
                            "target_table": "Customers",
                            "target_col": "customer_id",
                            "type": "inferred",
                            "confidence": 0.95
                        }
                    ]
                },
                "generated": {
                    "table_description": "Records purchase transactions placed by customers.",
                    "business_domain": "e-commerce",
                    "semantic_aliases": ["purchases", "sales", "transactions"],
                    "columns": {
                        "order_id": {
                            "description": "Unique transaction identifier for each order.",
                            "semantic_aliases": ["transaction ID", "invoice number"],
                            "business_role": "primary_key"
                        },
                        "customer_id": {
                            "description": "Foreign key pointing to the purchasing customer.",
                            "semantic_aliases": ["purchaser ID", "buyer reference"],
                            "business_role": "foreign_key"
                        },
                        "total_amount": {
                            "description": "Monetary value of the order transaction in dollars.",
                            "semantic_aliases": ["order price", "revenue", "sale amount"],
                            "business_role": "measure"
                        }
                    },
                    "common_questions": ["What is the total revenue?", "Show average order value."]
                }
            }
        }
    }


def test_embedding_model_and_dimensions():
    """Verifies that the embedding model loads, outputs 384 dimensions, is float32, and is L2-normalized."""
    model = semantic_embeddings.get_embedding_model()
    assert model is not None

    test_texts = ["Table: Customers", "Column: Orders.total_amount"]
    vectors = semantic_embeddings.generate_normalized_embeddings(test_texts, model=model)

    assert isinstance(vectors, np.ndarray)
    assert vectors.shape == (2, 384)
    assert vectors.dtype == np.float32

    # Verify L2 normalization (norm == 1.0)
    for i in range(vectors.shape[0]):
        norm = np.linalg.norm(vectors[i])
        assert np.isclose(norm, 1.0, atol=1e-5), f"Vector {i} norm is {norm}, expected 1.0"

    print("  PASS: test_embedding_model_and_dimensions")


def test_corpus_construction():
    """Verifies deterministic text generation and mapping for tables and columns."""
    meta = create_sample_metadata()
    texts, mapping = semantic_embeddings.create_embedding_corpus(meta)

    # 2 tables + (3 cols in Customers + 3 cols in Orders) = 2 + 6 = 8 items
    assert len(texts) == 8
    assert len(mapping) == 8

    # Table vectors
    table_items = [m for m in mapping if m["type"] == "table"]
    assert len(table_items) == 2
    assert {m["table"] for m in table_items} == {"Customers", "Orders"}

    # Column vectors
    col_items = [m for m in mapping if m["type"] == "column"]
    assert len(col_items) == 6
    assert any(m["column"] == "total_amount" for m in col_items)

    print("  PASS: test_corpus_construction")


def test_index_building_and_types():
    """Verifies FAISS IndexFlatIP construction, dimension, and vector counts."""
    meta = create_sample_metadata()

    with tempfile.TemporaryDirectory() as tmpdir:
        idx_path = os.path.join(tmpdir, "test.faiss")
        map_path = os.path.join(tmpdir, "test_mapping.json")
        meta_path = os.path.join(tmpdir, "test_meta.json")

        index, mapping, meta_doc = semantic_embeddings.build_index(
            metadata=meta,
            index_path=idx_path,
            mapping_path=map_path,
            meta_path=meta_path
        )

        assert isinstance(index, faiss.IndexFlatIP)
        assert index.d == 384
        assert index.ntotal == 8
        assert len(mapping) == 8
        assert meta_doc["vector_count"] == 8
        assert meta_doc["embedding_model"] == "all-MiniLM-L6-v2"

        # Verify files on disk
        assert os.path.exists(idx_path)
        assert os.path.exists(map_path)
        assert os.path.exists(meta_path)

    print("  PASS: test_index_building_and_types")


def test_index_save_load_and_staleness():
    """Verifies index loading from disk and staleness detection when metadata changes."""
    meta = create_sample_metadata()

    with tempfile.TemporaryDirectory() as tmpdir:
        meta_store_file = os.path.join(tmpdir, "metadata_store.json")
        idx_path = os.path.join(tmpdir, "test.faiss")
        map_path = os.path.join(tmpdir, "test_mapping.json")
        meta_path = os.path.join(tmpdir, "test_meta.json")

        with open(meta_store_file, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        # Build index
        semantic_embeddings.build_index(
            metadata=meta,
            index_path=idx_path,
            mapping_path=map_path,
            meta_path=meta_path
        )

        # 1. Fresh check
        assert semantic_embeddings.is_index_stale(idx_path, map_path, meta_path, meta_store_file) is False

        # 2. Load index
        loaded = semantic_embeddings.load_index(idx_path, map_path, meta_path, meta_store_file)
        assert loaded is not None
        index, mapping, meta_doc = loaded
        assert index.ntotal == 8

        # 3. Modify metadata store (e.g. timestamp) -> should become stale
        meta_modified = meta.copy()
        meta_modified["generated_at"] = "2026-08-17T12:00:00Z"
        with open(meta_store_file, "w", encoding="utf-8") as f:
            json.dump(meta_modified, f)

        assert semantic_embeddings.is_index_stale(idx_path, map_path, meta_path, meta_store_file) is True

    print("  PASS: test_index_save_load_and_staleness")


def test_retrieval_ranking_and_scores():
    """Verifies semantic retrieval returns ranked results with valid cosine scores."""
    meta = create_sample_metadata()

    with tempfile.TemporaryDirectory() as tmpdir:
        meta_store_file = os.path.join(tmpdir, "metadata_store.json")
        idx_path = os.path.join(tmpdir, "test.faiss")
        map_path = os.path.join(tmpdir, "test_mapping.json")
        meta_path = os.path.join(tmpdir, "test_meta.json")

        with open(meta_store_file, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        semantic_embeddings.build_index(
            metadata=meta,
            index_path=idx_path,
            mapping_path=map_path,
            meta_path=meta_path
        )

        # Query about revenue / order pricing
        results = semantic_embeddings.retrieve(
            query_text="What is the total order revenue amount?",
            top_k=3,
            metadata_path=meta_store_file,
            index_path=idx_path,
            mapping_path=map_path,
            meta_path=meta_path
        )

        assert len(results) == 3
        # Scores should be in descending order
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

        # Scores should be valid cosine similarity in [-1.0, 1.0] (typically > 0 for related concepts)
        for s in scores:
            assert -1.0 <= s <= 1.0

        # Top result should be related to Orders or total_amount
        top = results[0]
        assert top["table"] == "Orders"

    print("  PASS: test_retrieval_ranking_and_scores")


def test_retrieval_edge_cases():
    """Verifies retrieval edge cases: top_k <= 0, top_k > total vectors, empty query, empty metadata."""
    meta = create_sample_metadata()

    with tempfile.TemporaryDirectory() as tmpdir:
        meta_store_file = os.path.join(tmpdir, "metadata_store.json")
        idx_path = os.path.join(tmpdir, "test.faiss")
        map_path = os.path.join(tmpdir, "test_mapping.json")
        meta_path = os.path.join(tmpdir, "test_meta.json")

        with open(meta_store_file, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        semantic_embeddings.build_index(
            metadata=meta,
            index_path=idx_path,
            mapping_path=map_path,
            meta_path=meta_path
        )

        # 1. top_k <= 0
        assert semantic_embeddings.retrieve("query", top_k=0, metadata_path=meta_store_file, index_path=idx_path, mapping_path=map_path, meta_path=meta_path) == []
        assert semantic_embeddings.retrieve("query", top_k=-5, metadata_path=meta_store_file, index_path=idx_path, mapping_path=map_path, meta_path=meta_path) == []

        # 2. Empty string query
        assert semantic_embeddings.retrieve("", top_k=5, metadata_path=meta_store_file, index_path=idx_path, mapping_path=map_path, meta_path=meta_path) == []
        assert semantic_embeddings.retrieve("   ", top_k=5, metadata_path=meta_store_file, index_path=idx_path, mapping_path=map_path, meta_path=meta_path) == []

        # 3. top_k > total vectors (8 vectors in sample)
        res_large = semantic_embeddings.retrieve("customers", top_k=100, metadata_path=meta_store_file, index_path=idx_path, mapping_path=map_path, meta_path=meta_path)
        assert len(res_large) == 8  # capped at index size

        # 4. Empty metadata
        empty_meta_file = os.path.join(tmpdir, "empty_meta.json")
        with open(empty_meta_file, "w", encoding="utf-8") as f:
            json.dump({"tables": {}}, f)
        idx_empty = os.path.join(tmpdir, "empty.faiss")
        map_empty = os.path.join(tmpdir, "empty_map.json")
        meta_empty = os.path.join(tmpdir, "empty_meta_doc.json")

        semantic_embeddings.build_index({"tables": {}}, idx_empty, map_empty, meta_empty)
        res_empty = semantic_embeddings.retrieve("anything", top_k=5, metadata_path=empty_meta_file, index_path=idx_empty, mapping_path=map_empty, meta_path=meta_empty)
        assert res_empty == []

    print("  PASS: test_retrieval_edge_cases")


def test_rebuild_and_replace():
    """Verifies explicit rebuild replaces index and mapping correctly."""
    meta = create_sample_metadata()

    with tempfile.TemporaryDirectory() as tmpdir:
        meta_store_file = os.path.join(tmpdir, "metadata_store.json")
        idx_path = os.path.join(tmpdir, "test.faiss")
        map_path = os.path.join(tmpdir, "test_mapping.json")
        meta_path = os.path.join(tmpdir, "test_meta.json")

        with open(meta_store_file, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        # Initial build
        semantic_embeddings.build_index(meta, idx_path, map_path, meta_path)
        status1 = semantic_embeddings.get_index_status(meta_store_file, idx_path, map_path, meta_path)
        assert status1["vector_count"] == 8

        # Add a table to metadata
        meta2 = create_sample_metadata()
        meta2["tables"]["Products"] = {
            "observed": {"table_name": "Products", "row_count": 50, "column_count": 1, "columns": {"sku": {"type": "TEXT", "is_pk": True}}},
            "generated": {"table_description": "Inventory product catalog", "business_domain": "retail", "columns": {"sku": {"description": "Stock keeping unit"}}}
        }
        with open(meta_store_file, "w", encoding="utf-8") as f:
            json.dump(meta2, f)

        # Rebuild
        res = semantic_embeddings.rebuild_index(meta_store_file, idx_path, map_path, meta_path)
        assert res["status"] == "success"
        assert res["vector_count"] == 10  # 8 + 1 table + 1 col = 10

        status2 = semantic_embeddings.get_index_status(meta_store_file, idx_path, map_path, meta_path)
        assert status2["vector_count"] == 10
        assert status2["is_stale"] is False

    print("  PASS: test_rebuild_and_replace")


if __name__ == "__main__":
    print("\nRunning Semantic Embeddings & FAISS Test Suite...")
    test_embedding_model_and_dimensions()
    test_corpus_construction()
    test_index_building_and_types()
    test_index_save_load_and_staleness()
    test_retrieval_ranking_and_scores()
    test_retrieval_edge_cases()
    test_rebuild_and_replace()
    print("\nALL 7 TEST SUITES PASSED SUCCESSFULLY!\n")
