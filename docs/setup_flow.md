# Setup Flow

The setup experience is a **core deliverable**: a non-technical user should reach a
working app in one step. This document describes exactly what happens.

---

## The one command

```bash
./scripts/start.sh        # macOS / Linux
scripts\start.bat         # Windows
# — or, equivalently —
docker compose up --build
```

Then open **http://localhost:8501**.

---

## What the start script does (and why)

```
1. Check Docker is installed          → clear message + install link if missing
2. Check the Docker daemon responds   → "start Docker Desktop" if not running
3. Detect compose (plugin vs legacy)  → works on old and new Docker
4. Ensure .env exists                 → auto-copy from .env.example (no key needed)
5. Ensure data/ + logs/ dirs exist    → bind-mount targets on the host
6. docker compose up --build          → build image, start hardened container
```

Each step prints a friendly ✅ / ❌ line so a non-technical user can self-diagnose.

The two most common real-world failures for non-technical users — **Docker not
installed** and **Docker not running** — are both caught with actionable messages
before the build is attempted.

---

## First run vs. subsequent runs

- **First run** downloads the small local embedding model (~80 MB) into
  `data/model_cache/` once. This needs network access *that one time*; after that the
  app runs fully offline.
- **Subsequent runs** reuse the cached model and the persisted vector store in
  `data/chroma/`, so startup is fast and uploaded documents remain indexed.

---

## What the user does in the UI

1. **Upload** one or more `.txt` / `.md` / `.pdf` files (validated + auto-indexed).
2. **Ask** a question in the question box.
3. Read the **grounded answer** and expand the **Sources** to see exactly which
   document chunks supported it.

---

## Where things live (on the host)

```
data/uploads/      uploaded documents
data/chroma/       persistent vector store
data/model_cache/  downloaded embedding model
logs/audit.log.jsonl   structured audit trail
.env               local config (git-ignored; no secrets in V1)
```

These are bind-mounted into the container, so data and logs persist across restarts
and are inspectable from the host.

---

## Resetting

To start clean, stop the container and remove the runtime data:

```bash
docker compose down
rm -rf data/uploads/* data/chroma/* logs/*
```

(The directories themselves are kept via `.gitkeep`.)
