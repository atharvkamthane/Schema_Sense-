# SchemaSense Test Environment Specification

This document details the hardware, operating system, runtime, library, and framework configurations used during the validation and testing phase of SchemaSense AI.

All values recorded below are derived directly from the active runtime environment, dependency manifests, and repository configuration files.

---

## 1. Operating System & Platform

| Property | Value | Notes |
| :--- | :--- | :--- |
| **Operating System** | Windows 10 / Windows 11 64-bit | Platform identifier: `Windows-10-10.0.26200-SP0` |
| **Architecture** | x86_64 / AMD64 | 64-bit architecture |
| **Shell** | PowerShell / Windows Command Prompt | Commands executed using PowerShell terminal |
| **Local Timezone** | UTC+05:30 (IST) | System local time configuration |

---

## 2. Python Runtime & Virtual Environment

| Property | Value | Notes |
| :--- | :--- | :--- |
| **Python Version** | `3.10.0` | `tags/v3.10.0:b494f59, Oct 4 2021, 19:00:18` [MSC v.1929 64 bit (AMD64)] |
| **Virtual Environment Path** | `Backend/backend/.venv` | Isolated virtualenv created via standard `venv` module |
| **Package Manager** | `pip` version 26.2.1 | Package installer for Python |

---

## 3. Core Dependencies & Versions

| Package | Version | Purpose in SchemaSense |
| :--- | :--- | :--- |
| **`faiss-cpu`** | `1.15.0` | Native C++ dense vector similarity indexing (`IndexFlatIP`) |
| **`numpy`** | `1.26.4` | Numerical array manipulation and vector normalization |
| **`sentence-transformers`** | `3.1.0` | Transformer-based dense embedding generation |
| **`sqlglot`** | `30.17.0` | Dialect-aware SQL AST parsing, validation, and security checking |
| **`torch`** | `2.13.0` | Deep learning backend for transformer models |
| **`transformers`** | `4.57.6` | Hugging Face transformer pipeline support |
| **`pandas`** | `2.2.3` | Tabular data analysis and profiling |
| **`fastapi`** | `0.115.0` | High-performance asynchronous API web framework |
| **`uvicorn`** | `0.30.0` | ASGI web server implementation |
| **`starlette`** | `0.38.6` | Underlying ASGI toolkit powering FastAPI |
| **`pydantic`** | `2.13.4` | Data validation and settings management |
| **`sqlalchemy`** | `2.0.35` | Database reflection and connection pooling utilities |
| **`sqlite3`** | `3.35.5` (C SQLite engine) | Embedded relational database engine |
| **`httpx`** | `0.28.1` | HTTP client for asynchronous LLM/Ollama requests |
| **`requests`** | `2.32.3` | Synchronous HTTP communication library |
| **`python-dotenv`** | `1.0.1` | Environment variable management |

---

## 4. Vector Embedding & Retrieval Architecture

| Parameter | Configuration |
| :--- | :--- |
| **Model Name** | `sentence-transformers/all-MiniLM-L6-v2` |
| **Embedding Dimension** | 384 dimensions |
| **Vector Normalization** | $L_2$ normalized to unit length ($\|v\|_2 = 1.0$) |
| **Index Type** | `faiss.IndexFlatIP` (Flat Inner Product) |
| **Distance Metric** | Cosine Similarity (equivalent to inner product on normalized vectors) |
| **Vector Persistence** | `metadata_index.faiss` |
| **Entity Mapping** | `metadata_mapping.json` |
| **Index Metadata** | `metadata_index_meta.json` |
| **Default Retrieval Depth ($k$)** | 5 items (configurable up to index capacity) |

---

## 5. Large Language Model (LLM) & Ollama Configuration

| Parameter | Value | Source |
| :--- | :--- | :--- |
| **Serving Runtime** | Ollama Local Engine | Local HTTP daemon (`http://localhost:11434`) |
| **Active Model** | `qwen3.5:4b` | Defined in `Backend/backend/.env` (`OLLAMA_MODEL`) |
| **Keep-Alive Setting** | `10m` (`OLLAMA_KEEP_ALIVE=10m`) | Retains model weights in GPU VRAM between queries |
| **Reasoning Tokens** | `false` (`OLLAMA_THINK=false`) | Suppresses Qwen chain-of-thought tokens for fast SQL generation |
| **Target GPU Hardware** | NVIDIA GeForce RTX 3050 Laptop GPU (4 GB VRAM) | Documented in configuration comments |
| **Layer Offload Strategy** | Automatic full GPU layer offload | Managed by Ollama runtime |

---

## 6. Frontend Stack & Client Environment

| Technology | Version | Notes |
| :--- | :--- | :--- |
| **UI Framework** | React `19.2.4` | Configured in `package.json` |
| **Build Tool / Bundler** | Vite `8.0.1` | Modern frontend bundler |
| **Styling** | TailwindCSS `3.4.0`, PostCSS `8.4.0` | Utility-first CSS styling |
| **Routing** | React Router DOM `7.13.2` | Single-page application routing |
| **State Management** | Zustand `4.4.0` | Lightweight store management |
| **Animations** | Framer Motion `10.16.0` | UI component transitions |
| **Charts & Visualization** | Recharts `2.10.0`, Three.js `0.183.2` | Relational and analytical visualizations |
| **Authentication** | Clerk React `5.61.4` | User identity provider integration |

---

## 7. Database Engine Specifications

| Property | Value |
| :--- | :--- |
| **Engine** | SQLite |
| **Underlying C Library Version** | `3.35.5` |
| **Supported SQL Features** | CTEs (`WITH`), Window functions, Foreign Keys, Upsert |
| **Isolation Mode** | Read-Only connection for query execution |
| **Transaction Strategy** | Explicit rollback on failure; write access restricted to ingestion routines |
| **Active Storage Path** | `Backend/backend/database.sqlite` |

---

## 8. Unrecorded or Dynamic Parameters

The following parameters were either not recorded during testing or are determined at runtime:
- **Exact Host CPU Model:** Not recorded (x86_64 AMD64 architecture confirmed).
- **Exact Host Total RAM:** Not recorded (system supported multi-GB SQLite and torch model caches without swapping).
- **Network Latency to Ollama:** Local loopback (`127.0.0.1:11434`), negligible latency (< 2 ms).
