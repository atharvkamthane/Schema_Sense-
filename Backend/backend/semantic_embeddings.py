"""
Semantic Embeddings and FAISS Retrieval Layer for SchemaSense AI.

Builds a FAISS IndexFlatIP vector index from metadata_store.json using
all-MiniLM-L6-v2 embeddings with L2 normalization (cosine similarity).
Provides deterministic schema retrieval for natural language queries.
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

import semantic_metadata

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

DEFAULT_METADATA_PATH = "metadata_store.json"
DEFAULT_INDEX_PATH = "metadata_index.faiss"
DEFAULT_MAPPING_PATH = "metadata_mapping.json"
DEFAULT_META_PATH = "metadata_index_meta.json"

# Module-level model and index cache
_MODEL_CACHE: Optional[SentenceTransformer] = None
_CACHED_INDEX: Optional[faiss.IndexFlatIP] = None
_CACHED_MAPPING: Optional[List[Dict[str, Any]]] = None
_CACHED_META: Optional[Dict[str, Any]] = None


def get_embedding_model(model_name: str = EMBEDDING_MODEL_NAME) -> SentenceTransformer:
    """Lazy-loads and caches the sentence-transformers embedding model."""
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        logger.info(f"Loading embedding model: {model_name}")
        _MODEL_CACHE = SentenceTransformer(model_name)
    return _MODEL_CACHE


def build_table_embedding_text(table_name: str, table_data: Dict[str, Any]) -> str:
    """
    Constructs a deterministic, rich text representation of table-level semantic metadata.
    """
    obs = table_data.get("observed", {})
    gen = table_data.get("generated", {})

    desc = gen.get("table_description", "")
    domain = gen.get("business_domain", "")
    aliases = gen.get("semantic_aliases", [])
    aliases_str = ", ".join(aliases) if aliases else "None"

    # Summarize columns with their business roles
    cols_obs = obs.get("columns", {})
    cols_gen = gen.get("columns", {})
    col_summaries = []
    for cname, cdata in cols_obs.items():
        c_role = cols_gen.get(cname, {}).get("business_role") or "attribute"
        pk_str = " PK" if cdata.get("is_pk") else ""
        fk_str = " FK" if cdata.get("is_fk") else ""
        col_summaries.append(f"{cname} ({cdata.get('type', 'TEXT')}{pk_str}{fk_str}, {c_role})")
    cols_str = "; ".join(col_summaries) if col_summaries else "None"

    # Summarize relationships
    rels = obs.get("relationships", [])
    rel_summaries = []
    for r in rels:
        src_t = r.get("source_table") or r.get("source")
        src_c = r.get("source_col")
        tgt_t = r.get("target_table") or r.get("target")
        tgt_c = r.get("target_col")
        if src_t and tgt_t:
            rel_summaries.append(f"{src_t}.{src_c} -> {tgt_t}.{tgt_c}")
    rels_str = "; ".join(rel_summaries) if rel_summaries else "None"

    questions = gen.get("common_questions", [])
    questions_str = " | ".join(questions) if questions else "None"

    return (
        f"Table: {table_name}. "
        f"Description: {desc}. "
        f"Business Domain: {domain}. "
        f"Aliases: {aliases_str}. "
        f"Columns: {cols_str}. "
        f"Relationships: {rels_str}. "
        f"Common Questions: {questions_str}."
    ).strip()


def build_column_embedding_text(table_name: str, col_name: str, table_data: Dict[str, Any]) -> str:
    """
    Constructs a deterministic, rich text representation of column-level semantic metadata.
    """
    obs = table_data.get("observed", {})
    gen = table_data.get("generated", {})

    c_obs = obs.get("columns", {}).get(col_name, {})
    c_gen = gen.get("columns", {}).get(col_name, {})

    c_type = c_obs.get("type", "TEXT")
    c_desc = c_gen.get("description", "")
    c_role = c_gen.get("business_role", "attribute")
    c_aliases = c_gen.get("semantic_aliases", [])
    aliases_str = ", ".join(c_aliases) if c_aliases else "None"

    pk_str = "Primary Key" if c_obs.get("is_pk") else ""
    fk_ref = c_obs.get("fk_reference")
    fk_str = f"Foreign Key referencing {fk_ref}" if (c_obs.get("is_fk") or fk_ref) else ""
    key_info = ", ".join(filter(None, [pk_str, fk_str])) or "Regular column"

    samples = c_obs.get("sample_values", [])
    samples_str = ", ".join(repr(v) for v in samples[:4]) if samples else "None"

    top_vals = c_obs.get("top_values", [])
    top_str = ", ".join(f"{item.get('value')} ({item.get('count')})" for item in top_vals[:3]) if top_vals else "None"

    return (
        f"Column: {table_name}.{col_name}. "
        f"Type: {c_type}. "
        f"Description: {c_desc}. "
        f"Role: {c_role}. "
        f"Key Status: {key_info}. "
        f"Aliases: {aliases_str}. "
        f"Sample Values: [{samples_str}]. "
        f"Top Frequencies: [{top_str}]."
    ).strip()


def create_embedding_corpus(metadata: Dict[str, Any]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Transforms metadata_store.json into a parallel list of embedding texts and vector mappings.
    """
    texts: List[str] = []
    mapping: List[Dict[str, Any]] = []
    vector_id = 0

    tables = metadata.get("tables", {})
    if not isinstance(tables, dict):
        return texts, mapping

    for table_name, table_data in tables.items():
        if not isinstance(table_data, dict):
            continue

        # 1. Table-level vector
        table_text = build_table_embedding_text(table_name, table_data)
        texts.append(table_text)
        mapping.append({
            "vector_id": vector_id,
            "type": "table",
            "table": table_name,
            "column": None,
            "text_preview": table_text[:140],
        })
        vector_id += 1

        # 2. Column-level vectors
        obs_cols = table_data.get("observed", {}).get("columns", {})
        for col_name in obs_cols.keys():
            col_text = build_column_embedding_text(table_name, col_name, table_data)
            texts.append(col_text)
            mapping.append({
                "vector_id": vector_id,
                "type": "column",
                "table": table_name,
                "column": col_name,
                "text_preview": col_text[:140],
            })
            vector_id += 1

    return texts, mapping


def generate_normalized_embeddings(
    texts: List[str],
    model: Optional[SentenceTransformer] = None,
) -> np.ndarray:
    """
    Encodes text items using all-MiniLM-L6-v2, converts to float32, and L2-normalizes.
    Returns an (N, 384) numpy array where np.linalg.norm == 1.0 for each vector.
    """
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    if model is None:
        model = get_embedding_model()

    embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=False)
    embeddings = np.array(embeddings, dtype=np.float32)

    # Ensure L2 normalization so inner product equals cosine similarity
    faiss.normalize_L2(embeddings)
    return embeddings


def build_index(
    metadata: Dict[str, Any],
    index_path: str = DEFAULT_INDEX_PATH,
    mapping_path: str = DEFAULT_MAPPING_PATH,
    meta_path: str = DEFAULT_META_PATH,
    model: Optional[SentenceTransformer] = None,
) -> Tuple[faiss.IndexFlatIP, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Builds a FAISS IndexFlatIP from metadata dict and persists index, mapping, and meta files atomically.
    """
    texts, mapping = create_embedding_corpus(metadata)
    
    index = faiss.IndexFlatIP(EMBEDDING_DIM)
    
    if texts:
        vectors = generate_normalized_embeddings(texts, model=model)
        index.add(vectors)

    meta_doc = {
        "metadata_version": metadata.get("version", "1.0.0"),
        "metadata_generated_at": metadata.get("generated_at"),
        "database_fingerprint": metadata.get("database_fingerprint"),
        "embedding_model": EMBEDDING_MODEL_NAME,
        "embedding_dimension": EMBEDDING_DIM,
        "vector_count": index.ntotal,
        "table_vector_count": sum(1 for m in mapping if m["type"] == "table"),
        "column_vector_count": sum(1 for m in mapping if m["type"] == "column"),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }

    # Atomic Persistence
    _save_index_artifacts(index, mapping, meta_doc, index_path, mapping_path, meta_path)

    # Update memory cache
    global _CACHED_INDEX, _CACHED_MAPPING, _CACHED_META
    _CACHED_INDEX = index
    _CACHED_MAPPING = mapping
    _CACHED_META = meta_doc

    return index, mapping, meta_doc


def _save_index_artifacts(
    index: faiss.IndexFlatIP,
    mapping: List[Dict[str, Any]],
    meta_doc: Dict[str, Any],
    index_path: str,
    mapping_path: str,
    meta_path: str,
) -> None:
    """Atomically saves the FAISS index, vector mapping, and index metadata to disk."""
    pid = os.getpid()
    tmp_index = f"{index_path}.tmp.{pid}"
    tmp_mapping = f"{mapping_path}.tmp.{pid}"
    tmp_meta = f"{meta_path}.tmp.{pid}"

    try:
        # Write FAISS binary
        faiss.write_index(index, tmp_index)

        # Write mapping JSON
        with open(tmp_mapping, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)

        # Write meta JSON
        with open(tmp_meta, "w", encoding="utf-8") as f:
            json.dump(meta_doc, f, indent=2, ensure_ascii=False)

        # Atomic replacements with Windows retry
        for src, dst in [(tmp_index, index_path), (tmp_mapping, mapping_path), (tmp_meta, meta_path)]:
            replaced = False
            for _ in range(5):
                try:
                    os.replace(src, dst)
                    replaced = True
                    break
                except (PermissionError, OSError):
                    time.sleep(0.05)
            if not replaced:
                os.replace(src, dst)

    except Exception as e:
        for p in [tmp_index, tmp_mapping, tmp_meta]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        raise IOError(f"Failed to atomically persist FAISS index artifacts: {str(e)}") from e


def invalidate_semantic_cache() -> None:
    """Invalidates the in-memory FAISS index and vector mapping cache."""
    global _CACHED_INDEX, _CACHED_MAPPING, _CACHED_META
    _CACHED_INDEX = None
    _CACHED_MAPPING = None
    _CACHED_META = None
    logger.info("Semantic FAISS in-memory cache invalidated.")


def remove_index_artifacts(
    index_path: str = DEFAULT_INDEX_PATH,
    mapping_path: str = DEFAULT_MAPPING_PATH,
    meta_path: str = DEFAULT_META_PATH,
) -> None:
    """Deletes FAISS index, mapping, and meta files from disk and invalidates in-memory cache."""
    invalidate_semantic_cache()
    for p in [index_path, mapping_path, meta_path]:
        if os.path.exists(p):
            removed = False
            for _ in range(5):
                try:
                    os.remove(p)
                    removed = True
                    logger.info(f"Removed index artifact: {p}")
                    break
                except (PermissionError, OSError):
                    time.sleep(0.05)
            if not removed:
                logger.warning(f"Could not remove index artifact {p}")


def is_index_stale(
    index_path: str = DEFAULT_INDEX_PATH,
    mapping_path: str = DEFAULT_MAPPING_PATH,
    meta_path: str = DEFAULT_META_PATH,
    metadata_path: str = DEFAULT_METADATA_PATH,
    db_path: str = "database.sqlite",
) -> bool:
    """
    Checks if the FAISS index files exist and match the current metadata_store.json,
    and cascadingly verifies that metadata_store.json matches the active database.sqlite.
    """
    # 1. Cascading check: Is the metadata store itself stale or missing relative to the active database?
    # Only check active SQLite DB when using the default production store or when an explicit non-default DB path is specified
    is_default_store = os.path.abspath(metadata_path) == os.path.abspath(DEFAULT_METADATA_PATH)
    if is_default_store or db_path != "database.sqlite":
        if os.path.exists(db_path) and semantic_metadata.is_metadata_stale(metadata_path, db_path):
            return True

    # 2. Check if all index artifacts exist on disk
    if not (os.path.exists(index_path) and os.path.exists(mapping_path) and os.path.exists(meta_path)):
        return True

    if not os.path.exists(metadata_path):
        return True

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            index_meta = json.load(f)
        
        metadata = semantic_metadata.load_metadata(metadata_path)
        if not metadata:
            return True

        # Check metadata timestamp
        if index_meta.get("metadata_generated_at") != metadata.get("generated_at"):
            return True

        # Check database fingerprint
        meta_fp = metadata.get("database_fingerprint", {})
        idx_fp = index_meta.get("database_fingerprint", {})
        if meta_fp != idx_fp:
            return True

        # Check model and dimension consistency
        if index_meta.get("embedding_model") != EMBEDDING_MODEL_NAME or \
           index_meta.get("embedding_dimension") != EMBEDDING_DIM:
            return True

        return False

    except Exception:
        return True


def load_index(
    index_path: str = DEFAULT_INDEX_PATH,
    mapping_path: str = DEFAULT_MAPPING_PATH,
    meta_path: str = DEFAULT_META_PATH,
    metadata_path: str = DEFAULT_METADATA_PATH,
    db_path: str = "database.sqlite",
    force: bool = False,
) -> Optional[Tuple[faiss.IndexFlatIP, List[Dict[str, Any]], Dict[str, Any]]]:
    """
    Loads FAISS index and mapping from disk if available and fresh.
    Returns None if missing, corrupted, or stale (unless force=True).
    """
    global _CACHED_INDEX, _CACHED_MAPPING, _CACHED_META

    if not force and is_index_stale(index_path, mapping_path, meta_path, metadata_path, db_path=db_path):
        return None

    try:
        index = faiss.read_index(index_path)
        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping = json.load(f)
        with open(meta_path, "r", encoding="utf-8") as f:
            meta_doc = json.load(f)

        # Validate vector count consistency
        if index.ntotal != len(mapping):
            logger.warning(f"FAISS index count ({index.ntotal}) != mapping count ({len(mapping)})")
            return None

        _CACHED_INDEX = index
        _CACHED_MAPPING = mapping
        _CACHED_META = meta_doc
        return index, mapping, meta_doc

    except Exception as e:
        logger.error(f"Error loading FAISS index: {e}")
        return None


def get_or_build_index(
    metadata_path: str = DEFAULT_METADATA_PATH,
    index_path: str = DEFAULT_INDEX_PATH,
    mapping_path: str = DEFAULT_MAPPING_PATH,
    meta_path: str = DEFAULT_META_PATH,
    db_path: str = "database.sqlite",
) -> Tuple[faiss.IndexFlatIP, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Returns the active FAISS index and mapping, loading from disk or rebuilding automatically if stale.
    Performs full cascading check against database.sqlite and metadata_store.json.
    """
    global _CACHED_INDEX, _CACHED_MAPPING, _CACHED_META

    # Cascading synchronization: Ensure metadata_store.json matches active SQLite DB
    is_default_store = os.path.abspath(metadata_path) == os.path.abspath(DEFAULT_METADATA_PATH)
    if is_default_store or db_path != "database.sqlite":
        if os.path.exists(db_path) and semantic_metadata.is_metadata_stale(metadata_path, db_path):
            logger.info("Metadata is stale relative to database; regenerating metadata before retrieval.")
            invalidate_semantic_cache()
            metadata = semantic_metadata.generate_all_metadata(db_path=db_path, metadata_path=metadata_path, use_llm=False)
            return build_index(metadata, index_path, mapping_path, meta_path)

    # Return cached if valid and not stale
    if _CACHED_INDEX is not None and _CACHED_MAPPING is not None and not is_index_stale(index_path, mapping_path, meta_path, metadata_path, db_path=db_path):
        return _CACHED_INDEX, _CACHED_MAPPING, _CACHED_META or {}

    loaded = load_index(index_path, mapping_path, meta_path, metadata_path, db_path=db_path)
    if loaded is not None:
        return loaded

    # Rebuild from metadata_store.json
    metadata = semantic_metadata.load_metadata(metadata_path)
    if not metadata or ((is_default_store or db_path != "database.sqlite") and os.path.exists(db_path) and semantic_metadata.is_metadata_stale(metadata_path, db_path)):
        # If metadata_store.json does not exist yet or is stale, generate it first
        metadata = semantic_metadata.generate_all_metadata(db_path=db_path, metadata_path=metadata_path, use_llm=False)

    return build_index(metadata, index_path, mapping_path, meta_path)


def rebuild_index(
    metadata_path: str = DEFAULT_METADATA_PATH,
    index_path: str = DEFAULT_INDEX_PATH,
    mapping_path: str = DEFAULT_MAPPING_PATH,
    meta_path: str = DEFAULT_META_PATH,
) -> Dict[str, Any]:
    """
    Explicit rebuild function that loads current metadata_store.json and builds a fresh FAISS index.
    """
    metadata = semantic_metadata.load_metadata(metadata_path)
    if not metadata:
        raise FileNotFoundError(f"Cannot rebuild index: '{metadata_path}' does not exist.")

    _, mapping, meta_doc = build_index(metadata, index_path, mapping_path, meta_path)
    return {
        "status": "success",
        "message": f"FAISS index rebuilt successfully with {meta_doc.get('vector_count', 0)} vectors.",
        "vector_count": meta_doc.get("vector_count", 0),
        "table_vector_count": meta_doc.get("table_vector_count", 0),
        "column_vector_count": meta_doc.get("column_vector_count", 0),
        "embedding_model": EMBEDDING_MODEL_NAME,
        "built_at": meta_doc.get("built_at"),
    }


def retrieve(
    query_text: str,
    top_k: int = 10,
    metadata_path: str = DEFAULT_METADATA_PATH,
    index_path: str = DEFAULT_INDEX_PATH,
    mapping_path: str = DEFAULT_MAPPING_PATH,
    meta_path: str = DEFAULT_META_PATH,
    db_path: str = "database.sqlite",
    threshold: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves the top-k most semantically relevant table and column metadata entries for a query.
    Uses all-MiniLM-L6-v2 cosine similarity via L2-normalized FAISS IndexFlatIP search.
    """
    if top_k <= 0 or not query_text or not query_text.strip():
        return []

    try:
        index, mapping, _ = get_or_build_index(metadata_path, index_path, mapping_path, meta_path, db_path=db_path)
    except Exception as e:
        logger.error(f"Failed to obtain FAISS index for retrieval: {e}")
        return []

    if index.ntotal == 0 or not mapping:
        return []

    k = min(top_k, index.ntotal)

    # Encode and normalize query vector
    model = get_embedding_model()
    query_vec = model.encode([query_text.strip()], convert_to_numpy=True, normalize_embeddings=False)
    query_vec = np.array(query_vec, dtype=np.float32)
    faiss.normalize_L2(query_vec)

    # Search FAISS IndexFlatIP (returns inner products = cosine similarities)
    scores, indices = index.search(query_vec, k)

    # Resolve full metadata context
    metadata = semantic_metadata.load_metadata(metadata_path) or {}
    tables_meta = metadata.get("tables", {})

    results: List[Dict[str, Any]] = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(mapping):
            continue

        cos_score = float(score)
        if threshold is not None and cos_score < threshold:
            continue

        item = mapping[idx]
        tname = item["table"]
        cname = item.get("column")
        itype = item["type"]

        t_data = tables_meta.get(tname, {})
        t_obs = t_data.get("observed", {})
        t_gen = t_data.get("generated", {})

        result_entry: Dict[str, Any] = {
            "vector_id": int(idx),
            "type": itype,
            "table": tname,
            "column": cname,
            "score": round(cos_score, 4),
        }

        if itype == "table":
            result_entry["table_description"] = t_gen.get("table_description", "")
            result_entry["business_domain"] = t_gen.get("business_domain", "")
            result_entry["semantic_aliases"] = t_gen.get("semantic_aliases", [])
            result_entry["row_count"] = t_obs.get("row_count", 0)
            result_entry["column_count"] = t_obs.get("column_count", 0)
        elif itype == "column" and cname:
            col_obs = t_obs.get("columns", {}).get(cname, {})
            col_gen = t_gen.get("columns", {}).get(cname, {})
            result_entry["column_type"] = col_obs.get("type", "TEXT")
            result_entry["description"] = col_gen.get("description", "")
            result_entry["business_role"] = col_gen.get("business_role", "attribute")
            result_entry["semantic_aliases"] = col_gen.get("semantic_aliases", [])
            result_entry["is_pk"] = col_obs.get("is_pk", False)
            result_entry["is_fk"] = col_obs.get("is_fk", False)
            result_entry["fk_reference"] = col_obs.get("fk_reference")

        results.append(result_entry)

    return results


def get_index_status(
    metadata_path: str = DEFAULT_METADATA_PATH,
    index_path: str = DEFAULT_INDEX_PATH,
    mapping_path: str = DEFAULT_MAPPING_PATH,
    meta_path: str = DEFAULT_META_PATH,
    db_path: str = "database.sqlite",
) -> Dict[str, Any]:
    """Returns the current state and diagnostics of the FAISS vector index."""
    stale = is_index_stale(index_path, mapping_path, meta_path, metadata_path, db_path=db_path)
    meta_doc = None
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta_doc = json.load(f)
        except Exception:
            pass

    return {
        "index_exists": os.path.exists(index_path) and os.path.exists(mapping_path),
        "is_stale": stale,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "embedding_dimension": EMBEDDING_DIM,
        "vector_count": meta_doc.get("vector_count", 0) if meta_doc else 0,
        "table_vector_count": meta_doc.get("table_vector_count", 0) if meta_doc else 0,
        "column_vector_count": meta_doc.get("column_vector_count", 0) if meta_doc else 0,
        "built_at": meta_doc.get("built_at") if meta_doc else None,
    }


def sync_semantic_state(
    db_path: str = "database.sqlite",
    metadata_path: str = DEFAULT_METADATA_PATH,
    index_path: str = DEFAULT_INDEX_PATH,
    mapping_path: str = DEFAULT_MAPPING_PATH,
    meta_path: str = DEFAULT_META_PATH,
    use_llm: bool = False,
) -> Dict[str, Any]:
    """
    Synchronizes the complete semantic layer (metadata + FAISS index + mapping) with the active database.
    Invalidates in-memory caches, generates fresh metadata, and builds a fresh FAISS vector index.
    If generation or indexing fails, removes stale index artifacts so stale context is never served.
    """
    if not os.path.exists(db_path):
        remove_index_artifacts(index_path, mapping_path, meta_path)
        semantic_metadata.remove_metadata_artifacts(metadata_path)
        return {"status": "skipped", "reason": f"Database file '{db_path}' does not exist."}

    try:
        invalidate_semantic_cache()
        semantic_metadata.invalidate_metadata_cache()
        fresh_meta = semantic_metadata.generate_all_metadata(db_path=db_path, metadata_path=metadata_path, use_llm=use_llm)
        _, _, idx_meta = build_index(
            metadata=fresh_meta,
            index_path=index_path,
            mapping_path=mapping_path,
            meta_path=meta_path,
        )
        logger.info(f"Semantic state synchronized successfully with {len(fresh_meta.get('tables', {}))} tables.")
        return {
            "status": "synchronized",
            "table_count": len(fresh_meta.get("tables", {})),
            "tables": list(fresh_meta.get("tables", {}).keys()),
            "vector_count": idx_meta.get("vector_count", 0),
        }
    except Exception as e:
        logger.error(f"Semantic synchronization failed: {e}")
        remove_index_artifacts(index_path, mapping_path, meta_path)
        semantic_metadata.remove_metadata_artifacts(metadata_path)
        return {
            "status": "error",
            "error": str(e),
        }


def clear_semantic_state(
    metadata_path: str = DEFAULT_METADATA_PATH,
    index_path: str = DEFAULT_INDEX_PATH,
    mapping_path: str = DEFAULT_MAPPING_PATH,
    meta_path: str = DEFAULT_META_PATH,
) -> None:
    """
    Cleanses all semantic caches, metadata files, and FAISS index artifacts from memory and disk.
    """
    remove_index_artifacts(index_path, mapping_path, meta_path)
    semantic_metadata.remove_metadata_artifacts(metadata_path)

