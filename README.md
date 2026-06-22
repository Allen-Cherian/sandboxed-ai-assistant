# 🔒 Sandboxed AI Assistant

A **minimal, secure-by-default AI assistant environment**, demonstrated with a
**document Q&A** workload. Upload documents, ask questions, get answers grounded in
your documents — all inside a **hardened container**, **fully local**, with **no
external API and no credentials required**.

> The point of this project is the **secure execution model** and the
> **one-command setup**, not the chatbot. The Q&A workload is just the example.

---

## ✨ What it demonstrates

- **Sandboxed runtime** — hardened Docker container: non-root, read-only root
  filesystem, all Linux capabilities dropped, no privilege escalation, tmpfs `/tmp`.
- **Restricted filesystem** — the app writes *only* to a dedicated `data/` volume;
  every path is validated to stay inside it.
- **Least privilege / minimal tools** — the assistant can only `list_documents` and
  `retrieve_chunks`. No shell, no eval, no arbitrary file access.
- **Scoped secrets** — env-based config, `.env` git-ignored, secrets redacted from
  logs. V1 needs no secret at all.
- **Audit logging** — structured JSON-line logs of uploads, questions, retrievals,
  and errors.
- **One-command setup** — `docker compose up --build`.

See **`docs/security_model.md`** for the full security design and
**`docs/implementation_plan.md`** for the architecture.

---

## 🚀 Quick start

**Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(includes Docker Compose).

### Option A — helper script (recommended)

```bash
# macOS / Linux
./scripts/start.sh
```

```bat
REM Windows
scripts\start.bat
```

### Option B — plain Docker Compose

```bash
cp .env.example .env        # no API key needed — V1 is fully local
docker compose up --build
```

Then open **http://localhost:8501**.

> First build downloads a small local embedding model once (cached in
> `data/model_cache/`). Subsequent starts are fast.

---

## 🗂️ Project layout

```
app/        application code (UI, config, RAG pipeline, tools, security)
docs/       implementation plan, progress log, security model
data/        uploads/, chroma/, model_cache/  (the only writable area)
logs/       structured audit logs
scripts/    start.sh / start.bat  (one-command setup)
tests/      unit tests (e.g. filesystem-boundary policy)
```

---

---

## 🏗️ Architecture

```
┌── Hardened Docker container (non-root, read-only rootfs, cap_drop ALL,
│    no-new-privileges, noexec tmpfs, single writable volume) ───────────────┐
│                                                                            │
│  Streamlit UI (app/main.py)                                                │
│       │  (only ever calls the tool boundary — never the FS or a shell)     │
│  Tool boundary (app/tools/allowed_tools.py)  →  deny by default            │
│       │     allow-list = { list_documents, retrieve_chunks }               │
│  RAG pipeline (app/rag/*)         Security (app/security/file_policy.py)    │
│   loaders→splitter→embeddings→     confine every path to DATA_DIR           │
│   vector_store→retriever→qa        + type/size checks                       │
│       │                                                                    │
│  Writable volume  →  /app/data {uploads, chroma, model_cache} + /app/logs  │
└────────────────────────────────────────────────────────────────────────────┘
   Secrets: env-only (.env), redacted from logs. V1 needs none.
```

**Q&A flow:** question → `retrieve_chunks` (tool boundary) → local embedding →
ChromaDB top-k → extractive grounded answer + cited sources. Every step is audited.

Component reference:

| Area | Module | Responsibility |
|------|--------|----------------|
| Config | `app/config.py` | Env-based config + validation; defines the data boundary. |
| Startup | `app/startup.py` | Create writable dirs, redirect caches, configure logging. |
| Logging | `app/logger.py` | Structured JSON audit events; secret redaction. |
| FS boundary | `app/security/file_policy.py` | Path confinement, sanitization, type/size checks. |
| RAG | `app/rag/*` | loaders → splitter → embeddings → vector_store → retriever → qa. |
| Tools | `app/tools/*` | Deny-by-default capability allow-list. |
| UI | `app/main.py` | Streamlit shell; routes through the tool boundary only. |

See `docs/architecture.md` is summarized in `docs/implementation_plan.md` §3, and the
full security design in `docs/security_model.md`.

---

## 🔒 Security at a glance

| Boundary | Enforced by |
|----------|-------------|
| Sandboxed runtime | `docker-compose.yml` (read-only rootfs, `cap_drop: ALL`, `no-new-privileges`, tmpfs) + non-root `Dockerfile`. |
| Restricted filesystem | `app/security/file_policy.py` — every path confined to `data/`. |
| Least privilege | `app/tools/allowed_tools.py` — only `list_documents` + `retrieve_chunks`. |
| Scoped secrets | env-only, `.env` git/docker-ignored, redacted from logs; none required in V1. |
| Auditability | `app/logger.py` — structured JSON events in `logs/audit.log.jsonl`. |

### Audit events

Logged to stdout and `logs/audit.log.jsonl` (one JSON object per line):

`app_startup`, `upload_stored`, `upload_rejected`, `index_completed`, `index_failed`,
`question_asked`, `qa_failed`, `tool_invoked`, `tool_denied`, `tool_error`.

Secret-looking fields (`*_KEY`, `*_TOKEN`, `*_SECRET`, `PASSWORD`) are auto-redacted.

---

## ⚙️ Configuration

All optional — V1 runs with defaults and **no credentials**. Set in `.env`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATA_DIR` | `/app/data` | The single writable data directory (boundary root). |
| `LOG_DIR` | `/app/logs` | Audit log directory. |
| `ALLOWED_EXTENSIONS` | `.txt,.md,.pdf` | Upload type allow-list. |
| `MAX_UPLOAD_MB` | `10` | Per-file size limit. |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local sentence-transformers model. |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `800` / `120` | Chunking. |
| `RETRIEVAL_TOP_K` | `4` | Chunks retrieved per question. |
| `APP_ENV` | `production` | Environment label (logged). |
| `LOG_LEVEL` | `INFO` | Logging verbosity. |

---

## 🧪 Tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

The suite covers the security-critical boundaries (filesystem confinement, tool
allow-list) and the RAG text path. The embedding/vector-store path runs at container
runtime.

---

## 🧭 Status

Built in phases (see `docs/progress_log.md`). The app is **end-to-end functional**:
upload → index → ask → grounded answer with sources, inside the hardened sandbox.

## ⚠️ Limitations (V1)

No authentication, no prompt-injection defense, single-tenant, Docker-default
syscall filtering. See `docs/security_model.md` §8 and `docs/threat_model.md` for the
full, honest list.
