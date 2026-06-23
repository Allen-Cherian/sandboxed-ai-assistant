# Project Summary

A plain-English-but-technical summary of what this project is. For the full design
see `implementation_plan.md` (architecture), `security_model.md` (boundaries), and
`threat_model.md` (assumptions).

---

## One-paragraph summary

A **fully-local, containerized document Q&A web app that demonstrates a
secure-by-default AI execution model.** A user uploads documents through a Streamlit
UI; the app extracts and chunks the text, converts each chunk into vectors using a
local embedding model (`all-MiniLM-L6-v2`), and stores them in a local vector
database (ChromaDB). When the user asks a question, the app embeds the question,
retrieves the most similar chunks, and returns them as a ranked, cited answer
(extractive — **no text-generating LLM**). The entire app runs inside a hardened
Docker container and is constrained by three enforced security boundaries: a
**deny-by-default tool allow-list**, a **filesystem guard** confining all access to
one data folder, and **container hardening** (non-root, read-only root filesystem,
dropped capabilities, no network).

---

## Technical essentials

| Aspect | What it is, technically |
|--------|------------------------|
| **Type** | Local web app (Streamlit) + RAG pipeline, packaged as a Docker container. |
| **Workload** | Retrieval-Augmented document Q&A (upload → chunk → embed → store → retrieve). |
| **AI element** | A local sentence-transformer **embedding model** for semantic search — *not* a generative LLM. |
| **Answering** | **Extractive**: returns the top-k most relevant chunks with similarity scores + sources. |
| **Storage** | Local vector DB (ChromaDB), persisted to one `data/` directory. No external services. |
| **Security model** | Three independent boundaries: tool allow-list (least privilege), filesystem confinement, container hardening. |
| **Secrets** | Environment-based config; none required (fully offline). |
| **Observability** | Structured JSON audit logging of every meaningful action. |
| **Setup** | One command (`docker compose up`) — single-step for a non-technical user. |

---

## Data flow

```
Upload → extract text → chunk → embed (local model) → store (ChromaDB)
Ask    → embed question → find nearest chunks → return ranked, cited passages
```

…with **every** file operation passing through the filesystem guard, and **every**
assistant action passing through the two-function tool allow-list — all inside the
Docker cage.

---

## The three security walls

1. **Tool allow-list** (`app/tools/allowed_tools.py`) — the assistant can only call
   `list_documents` and `retrieve_chunks`. Everything else is denied by default; no
   shell, eval, network, or arbitrary file access exists in the code.
2. **Filesystem guard** (`app/security/file_policy.py`) — every path is confined to
   the `data/` directory; traversal, symlink escape, wrong type, and oversize uploads
   are rejected (and tested).
3. **Container hardening** (`docker-compose.yml` + `Dockerfile`) — non-root user,
   read-only root filesystem, all Linux capabilities dropped, no privilege escalation,
   noexec tmpfs, single writable volume, no outbound network.

---

## Shortest possible version

> **A secure-by-default, fully-local RAG document-Q&A app in a hardened Docker
> container, where the AI assistant is confined to two read-only capabilities and one
> data folder.**
