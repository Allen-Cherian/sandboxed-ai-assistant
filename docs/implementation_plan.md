# Implementation Plan — Minimal Sandboxed AI Assistant

> **Status:** ✅ V1 complete (all 8 phases). See `progress_log.md` for the phase log.
> **Last updated:** 2026-06-22

---

## 1. Project Goal

Build a **Minimal Sandboxed AI Assistant** that demonstrates a **secure-by-default
AI assistant environment**. The example workload is a **document Q&A assistant**
(upload documents → ask questions → get grounded answers with sources), but the
*primary* deliverable is the **secure execution model** and the **one-command
setup experience**, not the AI features.

The project should make the following concrete and visible:

1. Sandboxed runtime (containerized, non-root, restricted)
2. Controlled permissions / least privilege
3. Restricted filesystem access (dedicated data directory only)
4. Minimal, explicit tool access
5. Scoped secret handling (env-based, never logged)
6. Basic audit logging
7. Single-command setup for a non-technical user

---

## 2. Scope of V1

### In scope

- Streamlit browser UI.
- Upload `.txt`, `.md`, and `.pdf` documents.
- Chunk + embed + index documents in a local vector store.
- Ask questions; retrieve relevant chunks; generate a grounded answer.
- Display source chunks / references used for the answer.
- Containerized runtime with hardening (non-root, read-only FS, dropped caps).
- Dedicated `data/` directory for uploads, vector DB, and logs.
- Explicit tool/capability allow-list (retrieve, list — nothing else).
- Env-based secret handling with `.env.example` template + startup validation.
- Structured audit logging of uploads, questions, retrievals, errors.
- One-command setup (`docker compose up --build`) + helper start scripts.
- Planning/security/progress docs kept continuously up to date.

### Explicitly OUT of scope for V1 (see §9)

Browser/coding/shell agents, multi-agent orchestration, auth/RBAC, advanced
prompt-injection defenses, provenance tooling, Kubernetes hardening, cloud deploy.

---

## 3. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│  Docker container (non-root user, read-only rootfs,          │
│  no-new-privileges, dropped caps, single writable volume)    │
│                                                              │
│   ┌────────────────────────────────────────────────────┐    │
│   │  Streamlit UI (app/main.py)                        │    │
│   │   • upload widget   • question box   • sources view │    │
│   └───────────────┬────────────────────────────────────┘    │
│                   │ calls ONLY allowed tools                 │
│   ┌───────────────▼────────────────────────────────────┐    │
│   │  Tool boundary (app/tools/allowed_tools.py)        │    │
│   │   registry = { list_documents, retrieve_chunks }   │    │
│   │   ⟵ no shell / no eval / no arbitrary FS            │    │
│   └───────────────┬────────────────────────────────────┘    │
│                   │                                          │
│   ┌───────────────▼─────────┐   ┌────────────────────────┐  │
│   │ RAG pipeline (app/rag)  │   │ Security (app/security)│  │
│   │  loaders → splitter →   │   │  file_policy: confine  │  │
│   │  embeddings → vector_   │   │  every path to DATA_DIR│  │
│   │  store → retriever → qa │   │  + type/size checks    │  │
│   └───────────┬─────────────┘   └────────────────────────┘  │
│               │                                              │
│   ┌───────────▼──────────────────────────────────────────┐ │
│   │  Writable volume  ⟶  /app/data  (bind-mounted host    │ │
│   │   ./data)                                             │ │
│   │   uploads/   chroma/   ../logs/                       │ │
│   └──────────────────────────────────────────────────────┘ │
│                                                              │
│  Secrets: injected via env (.env) — validated at startup,   │
│  never written to logs.                                      │
└──────────────────────────────────────────────────────────────┘
```

**Request flow (Q&A):** UI question → `retrieve_chunks` tool → retriever queries
ChromaDB → top-k chunks → `qa` builds a grounded prompt → LLM → answer + sources
back to UI. Every step emits an audit log line.

---

## 4. Security Goals

| # | Goal | How V1 achieves it |
|---|------|--------------------|
| A | Sandboxed runtime | Docker; non-root `appuser`; `read_only: true` rootfs; `cap_drop: ALL`; `no-new-privileges`; tmpfs for `/tmp`; single writable volume. |
| B | Least privilege | App only ever calls tools in an explicit allow-list registry. No shell/eval/network-tool primitives exposed to the assistant. |
| C | Restricted filesystem | `security/file_policy.py` resolves & validates every path under `DATA_DIR`; rejects traversal/symlink escapes; enforces type + size on upload. |
| D | Scoped secrets | Config loaded from env/`.env`; `.env.example` documents keys; startup validation; secret values redacted from logs; `.env` git-ignored. |
| E | Auditability | `app/logger.py` emits structured (JSON) events: upload, question, retrieval, answer-metadata, error. Logs land in the dedicated `logs/` dir. |

Full detail and threat assumptions in `security_model.md`.

---

## 5. Setup / One-Command UX Goal

Target experience for a non-technical user:

1. Download/clone the repo.
2. `cp .env.example .env` (no API key required — V1 is fully local).
3. Run **one** command: `docker compose up --build` — or `./scripts/start.sh`
   (`scripts\start.bat` on Windows).
4. Open `http://localhost:8501`.

The start scripts: check `.env` exists (offer to copy from example), create missing
`data/`+`logs/` dirs, warn clearly on missing/placeholder config, then launch compose.

**Fully local, zero-key:** V1 uses **local embeddings** (sentence-transformers) and
**extractive answering** (best-matching chunks composed into a grounded answer). No
external API and no secret is required to run the full demo. `.env` still exists to
demonstrate the scoped-secret *pattern* (e.g. an optional model name / config), but
contains no credentials in V1.

---

## 6. Project Structure

```
sandboxed-ai-assistant/
├─ app/
│  ├─ main.py            # Streamlit UI shell + wiring
│  ├─ config.py          # env-based config + validation
│  ├─ startup.py         # dir creation, env checks, preflight
│  ├─ logger.py          # structured audit logging
│  ├─ rag/
│  │  ├─ loaders.py      # read txt/md/pdf safely
│  │  ├─ splitter.py     # chunking
│  │  ├─ embeddings.py   # local embeddings (sentence-transformers)
│  │  ├─ vector_store.py # ChromaDB wrapper
│  │  ├─ retriever.py    # top-k retrieval
│  │  └─ qa.py           # grounded answer generation
│  ├─ tools/
│  │  ├─ allowed_tools.py   # explicit registry / dispatcher
│  │  └─ document_tools.py  # list_documents, retrieve_chunks impls
│  ├─ security/
│  │  └─ file_policy.py  # path confinement + type/size checks
│  └─ utils/
│     └─ __init__.py
├─ docs/
│  ├─ implementation_plan.md
│  ├─ progress_log.md
│  ├─ security_model.md
│  ├─ setup_flow.md          (optional, Phase 6)
│  └─ threat_model.md        (optional, Phase 6)
├─ data/
│  ├─ uploads/   (.gitkeep)
│  └─ chroma/    (.gitkeep)
├─ logs/         (.gitkeep)
├─ scripts/
│  ├─ start.sh
│  └─ start.bat
├─ tests/
│  └─ test_file_policy.py
├─ Dockerfile
├─ docker-compose.yml
├─ .env.example
├─ .dockerignore
├─ .gitignore
├─ requirements.txt
└─ README.md
```

---

## 7. Phased Implementation Plan

| Phase | Name | Key outputs |
|-------|------|-------------|
| 0 | Planning | The 3 docs (this file, progress, security). |
| 1 | Skeleton + setup foundation | Structure, Dockerfile, compose, `.env.example`, config, startup checks, minimal Streamlit shell, start scripts, README skeleton. |
| 2 | Upload + safe storage boundary | Upload UI, type/size checks, `file_policy` confinement, upload logging. |
| 3 | Chunking + embeddings + vector store | loaders, splitter, local embeddings (sentence-transformers), ChromaDB store, metadata. |
| 4 | Retrieval + Q&A loop | question input, retrieval, grounded answer gen, answer + sources display. |
| 5 | Explicit tool boundary | allow-list registry; assistant gets only `list_documents` + `retrieve_chunks`. |
| 6 | Logging + setup polish + security writeup | structured logging, env validation polish, start-script polish, README + security docs. |
| 7 | Review / cleanup / final docs | finalize docs, verify E2E runnable, limitations + future work. |

After **every** phase: update `progress_log.md`; update `implementation_plan.md`
/`security_model.md` if anything material changed.

---

## 8. Risks / Open Questions

| Risk / question | Mitigation / decision |
|-----------------|-----------------------|
| Fully-local answers are weaker than an LLM. | V1 uses **extractive** answering (compose top chunks + citations), framed honestly in the UI/docs; LLM answering is a documented future extension. |
| `read_only` rootfs can break libs that write to cwd/home. | Mount tmpfs `/tmp`; point caches (HF/Chroma) into the writable volume via env (`HF_HOME`, etc.). |
| PDF parsing is a common attack surface. | Keep PDF optional; use a pure-Python parser; enforce size limits; never execute embedded content. |
| Local embedding model download size/time. | Use a small model (`all-MiniLM-L6-v2`); cache into the writable volume; document the one-time first-run download. |
| Streamlit reruns can duplicate side effects. | Guard indexing/logging with idempotency keys (file hash). |
| Path traversal / symlink escape on upload. | Centralize in `file_policy`; resolve realpath; assert it's within `DATA_DIR`. |

---

## 9. Intentionally Out of Scope for V1

- Browser agents, coding agents, shell-execution tools.
- Multi-agent orchestration.
- Authentication / RBAC / multi-tenant isolation.
- Advanced prompt-injection defenses (documented as a known limitation).
- Provenance/supply-chain tooling integration.
- Kubernetes-level hardening, seccomp/AppArmor profile authoring.
- Production cloud deployment, TLS termination, horizontal scaling.

These are noted as **future extensibility** directions, not V1 work.

---

## 10. Change Log (plan-level)

- **2026-06-22** — Initial plan authored (Phase 0). Chose Python/Streamlit/ChromaDB
  per suggested stack.
- **2026-06-22** — User decisions: **fully-local** provider (no external API at all)
  and **full container hardening**. Removed all API-key happy-path; V1 uses local
  sentence-transformers embeddings + extractive answering. `.env` retained to
  demonstrate the scoped-secret pattern but holds no credentials. LLM-backed
  answering moved to future extensibility.
- **2026-06-22** — Phases 1–7 implemented. V1 complete: end-to-end document Q&A
  inside the hardened sandbox, deny-by-default tool boundary, tested FS boundary,
  structured audit logging, one-command setup, full docs (incl. `setup_flow.md`,
  `threat_model.md`). 47 unit tests passing. Final review (parallel code + docs
  audits) found no security issues; minor doc gaps and Q&A error-handling robustness
  fixed.
