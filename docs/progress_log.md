# Progress Log — Minimal Sandboxed AI Assistant

A continuously-updated record of implementation. Newest entries at the top of each
phase section. See `implementation_plan.md` for the full plan and
`security_model.md` for the security design.

---

## Current Status Summary

- **Status:** ✅ V1 complete & verified. **LLM phase: Steps 1–5 done** (code +
  docs complete). Only Step 6 remains: **live M4 check** (install Ollama, pull model,
  toggle Generated) — needs your hardware.
- **LLM phase tests:** 63 passing (47 V1 + 16 new LLM). UI is Streamlit (not unit
  tested); import graph verified clean.

- **Status (V1):** ✅ **V1 COMPLETE & VERIFIED RUNNING** — all 8 phases done; confirmed
  end-to-end on real hardware (Apple Silicon, Docker) on 2026-06-22.
- **Overall:** Live demo works: README.md uploaded → indexed (12 chunks) → question
  asked → grounded passages returned with relevance scores + source attribution, fully
  local inside the hardened container. Deny-by-default tool boundary, tested filesystem
  boundary, structured audit logging, one-command setup. **47 unit tests passing.**
- **Answer behavior:** extractive (ranked, cited chunks) by design — fully-local,
  no LLM. Low-ish similarity scores on broad questions are expected, not a defect.
- **Blockers:** none.
- **Next step:** none for V1 (user chose to stop here). Future extensibility — better
  extractive tuning, local/API LLM answerer — listed in plan §9 / threat model §4.

---

## LLM Phase — Step 1–2: config, scoped egress, provider abstraction  ✅ (2026-06-23)

Adds an **optional** local-LLM answering backend (default OFF). Plan:
`docs/phase_llm_plan.md`.

**Completed**
- `app/config.py` — new LLM config (all defaulted, so existing constructors/tests
  are untouched): `LLM_ENABLED` (default false), `LLM_PROVIDER` (ollama),
  `LLM_MODEL` (llama3.2:1b), `LLM_BASE_URL`, `LLM_TIMEOUT_S`, `LLM_MAX_TOKENS`.
  Validation runs **only when enabled**; rejects unknown provider + malformed
  `LLM_BASE_URL` (must be a valid http(s) URL — the single permitted call target).
- `app/rag/llm/__init__.py` — `LLMProvider` interface (`generate`/`health`) +
  `get_provider(cfg)` factory (deny unknown) + `provider_health` helper. The LLM is
  a **text generator, not an agent** — gets no tools.
- `app/rag/llm/ollama_provider.py` — `OllamaProvider` via stdlib `urllib` (no new
  dep). Security props: single config-controlled destination, **hard timeout**,
  **response-size cap** (`num_predict`), clear errors, non-raising `health()`.
- `app/rag/llm/api_providers.py` — Anthropic/OpenAI reserved slots that raise a clear
  `NotImplementedError`-style `LLMError` pointing to plan §10.
- `app/startup.py` — audit event now includes LLM fields; **non-blocking**
  `_check_llm_reachable` (only when enabled) logs `llm_health` and never crashes.
- `docker-compose.yml` — `extra_hosts: host.docker.internal:host-gateway` (localhost
  mapping to host Ollama; **not** general internet egress).
- `.env.example` — documented all `LLM_*` vars + host setup (install Ollama, pull
  model) + reserved API-key slots.

**Verification**
- `pytest tests/` → **58 passed** (47 V1 + 11 new in `test_llm_config_provider.py`:
  config defaults/validation, provider selection, Ollama generate/empty/unreachable,
  health). ✅
- Startup smoke test (LLM **disabled**) → boots, audit shows `llm_enabled:false`. ✅
- Startup smoke test (LLM **enabled, Ollama unreachable**) → boots anyway, logs
  `llm_health reachable:false` with reason, **no crash**. ✅ (graceful degradation)
- All 21 app modules AST-parse. ✅

**Decisions / tradeoffs**
- LLM fields **defaulted + moved to end** of the `Config` dataclass so the 6 new
  fields don't break existing keyword-based `Config(...)` constructions in tests.
- Used **stdlib `urllib`** for the Ollama client — no new dependency, and no HTTP
  client that could silently reach a different host.
- Wrote the `OllamaProvider` (nominally Step 2) now because Step 1's reachability
  check needs its `health()`.

**Remaining next (Step 3+)**
- `qa.py`: `answer_question_llm` — grounded, injection-resistant prompt →
  `get_provider().generate()` → answer + same sources. Step 4: UI toggle + fallback.
  Step 5: security/threat/README docs. Step 6: tests + live M4 check.

**Risks / blockers** — none. Live container→host-Ollama call is only verifiable on
the M4 (no Docker/Ollama in this authoring env); code degrades gracefully if down.

---

## LLM Phase — Step 3: LLM answering in qa.py  ✅ (2026-06-23)

**Completed**
- `app/rag/qa.py` — added `answer_question_llm(...)` alongside the unchanged
  extractive `answer_question(...)`. Both share `_retrieve_relevant()` (same tool
  boundary). `Answer` gained `mode` ("extractive"|"llm") and `note` fields.
- **Injection-resistant prompt** (`_build_grounded_prompt` + `_SYSTEM_INSTRUCTION`):
  context wrapped in explicit `BEGIN/END CONTEXT (untrusted document data)`
  delimiters; system rules say use ONLY the context, treat context as data not
  instructions, never obey directives found inside it, and say so if the answer
  isn't present. (Plan §5 mitigations 1–2.)
- **Grounding gate:** if retrieval finds nothing relevant, the LLM is **not invoked**
  at all (no ungrounded generation) — returns the same no-match message.
- **Graceful fallback:** any LLM failure (unbuilt/unreachable/timeout/empty) returns
  the extractive answer with an explanatory `note`. The user always gets an answer.
- Lazy `from app.rag.llm import get_provider` inside the LLM path so the extractive
  path never depends on the LLM layer.

**Verification**
- `pytest tests/` → **63 passed** (+5 in `test_qa_llm.py`: grounded LLM answer,
  fallback on failure, fallback on empty, no-match skips the LLM entirely,
  injection-resistant prompt shape). ✅
- `qa.py` AST-parses. ✅

**Decisions / tradeoffs**
- LLM is invoked **only when there's grounding** — both a quality and a security
  choice (no ungrounded hallucination; smaller injection surface).
- Fallback preserves UX: an LLM outage silently degrades to V1 behavior + a note,
  never an error page.

**Remaining next (Step 4+)**
- UI: a mode toggle (Extractive ⟷ Generated), enabled only when `LLM_ENABLED` and the
  provider is healthy; show `note` on fallback; new audit fields (mode/model/latency).
  Then Step 5 (docs) + Step 6 (live M4 check).

**Risks / blockers** — none.

---

## LLM Phase — Step 4: UI toggle + fallback + audit  ✅ (2026-06-23)

**Completed**
- `app/main.py` — `_render_mode_selector(cfg)`: shows an **Answer mode** radio
  (Extractive ⟷ Generated) **only** when `LLM_ENABLED` *and* the provider is reachable.
  If enabled-but-unreachable, shows a caption and silently stays extractive (V1
  default). Health probe cached in `st.session_state` so it doesn't run every rerun.
- `_render_ask` routes to `answer_question_llm` or `answer_question` per the toggle;
  times the call (`time.monotonic`); displays the fallback `note` (if any) as a
  warning above the answer.
- Richer `question_asked` audit: `mode`, `model` (only when llm), `grounded`,
  `latency_ms`, `fell_back`, plus the existing per-source name/score. `qa_failed`
  now records `mode` too.
- Import cleanup (`time` with stdlib imports; new `provider_health` / `answer_question_llm`).

**Verification**
- `pytest tests/` → **63 passed** (UI itself is Streamlit, not unit-tested). ✅
- `main.py` AST-parses; full app import graph resolves cleanly (no circular imports,
  no missing symbols). ✅

**Decisions / tradeoffs**
- The LLM toggle only appears when the backend is actually usable — a non-technical
  user never sees an option that would just error. Default selection is Extractive.
- Health cached per session (not per rerun) to avoid probing Ollama on every keystroke.

**Remaining next (Step 5–6)**
- Step 5: update `security_model.md` (egress + LLM mode + injection mitigation),
  `threat_model.md`, README (LLM section + setup), and the audit-event list.
- Step 6: live check on the M4 (install Ollama, pull `llama3.2:1b`, toggle Generated).

**Risks / blockers** — none. The container→host-Ollama call + model quality are only
verifiable live on the M4.

---

## LLM Phase — Step 5: documentation  ✅ (2026-06-23)

**Completed**
- `docs/security_model.md` — added **§7 Optional LLM Answering Mode** (off-by-default,
  text-generator-not-agent, local-only egress, bounded execution, grounding gate,
  basic injection mitigation, future-API-provider caveat). Updated §2 (scoped opt-in
  egress), §4 (LLM downstream of allow-list, no tools), §6 (new audit fields), §8
  (egress note), §9 (injection now *partially* mitigated). Renumbered Threat
  Assumptions→§8, Limitations→§9, Change Log→§10; fixed cross-refs. Numbering verified
  clean (1–10, no collisions).
- `docs/threat_model.md` — header now covers default + LLM mode; §3 updated
  (data-exfil now local-only incl. Ollama; DoS row includes LLM timeout/cap; **new
  prompt-injection (LLM mode) row**); §4 reframed "full injection defense" as the
  accepted gap.
- `README.md` — new **"🤖 Optional: generated answers with a local LLM"** section
  (host setup: install Ollama + pull model + enable; security summary; cloud-provider
  caveat). Added `llm_health` to the audit list, the `LLM_*` rows to the config table,
  and `phase_llm_plan.md` + `agentic_future.md` to the Documentation index.

**Verification**
- `pytest tests/` → **63 passed** (docs-only changes; nothing referenced a renamed
  symbol). ✅
- Security-model section numbering verified contiguous 1–10. ✅

**Remaining next (Step 6 — needs the M4)**
- Install Ollama on the host, `ollama pull llama3.2:1b`, set `LLM_ENABLED=true`,
  rebuild, toggle **Generated**, confirm a grounded written answer + the audit
  `mode:llm` / `latency_ms` fields, and confirm graceful fallback when Ollama is off.

**Risks / blockers** — none. Step 6 is a live hardware check only.

---

## Phase 0 — Planning  ✅ (2026-06-22)

**Completed**
- Analyzed the project requirements and summarized understanding.
- Created `docs/implementation_plan.md` (goal, scope, architecture, security
  goals, setup UX, structure, 8-phase plan, risks, out-of-scope).
- Created `docs/progress_log.md` (this file).
- Created `docs/security_model.md` (runtime/FS/tool/secret/logging boundaries +
  limitations).
- Proposed repo structure and phased plan.

**Files added**
- `docs/implementation_plan.md`
- `docs/progress_log.md`
- `docs/security_model.md`

**Decisions / tradeoffs**
- Stack confirmed: Python + Streamlit + ChromaDB (matches suggested stack).
- Added a **zero-API-key local fallback** (local embeddings + extractive answers)
  so the security demo runs offline. Justification: setup simplicity and
  secure-by-default both improve when the happy path needs no external secret.
- API-backed answer mode uses **Claude (latest model)** via the Anthropic API.

**Remaining next**
- Phase 1: structure, Dockerfile, docker-compose, `.env.example`, config loading,
  startup checks, minimal Streamlit shell, start scripts, README skeleton.

**Risks / blockers**
- None yet. Watch: read-only rootfs vs. library write paths (mitigated by tmpfs +
  cache redirection into the writable volume).

---

## Phase 1 — Project skeleton + setup foundation  ✅ (2026-06-22)

**Completed**
- Full repo structure created (`app/{rag,tools,security,utils}`, `data/`, `logs/`,
  `scripts/`, `tests/`) with package `__init__.py` files and `.gitkeep`s.
- `app/config.py` — env-based config + validation; defines the filesystem boundary
  (single `DATA_DIR`), upload policy, RAG params. No hardcoded secrets; V1 needs none.
- `app/logger.py` — structured JSON-line audit logging to stdout + `logs/audit.log.jsonl`;
  redacts any field whose key matches secret-name patterns.
- `app/startup.py` — preflight: creates the writable dirs, redirects HF/ST model
  caches into the writable volume (required by read-only rootfs), configures logging,
  emits an `app_startup` audit event.
- `app/main.py` — minimal Streamlit shell: runs preflight, shows security posture +
  config in the sidebar.
- `Dockerfile` — slim base, deps as root, runs as non-root `appuser` (uid 10001),
  owns only the writable dirs; healthcheck on Streamlit's health endpoint.
- `docker-compose.yml` — **sandbox enforced here:** `read_only: true`,
  `cap_drop: [ALL]`, `no-new-privileges`, tmpfs `/tmp` (noexec,nosuid), single
  `./data` + `./logs` bind mount, cpu/mem limits.
- `.env.example` (no credentials), `.gitignore`, `.dockerignore`.
- `scripts/start.sh` + `scripts/start.bat` — one-command setup: check Docker, create
  `.env` from template if missing, create dirs, `docker compose up --build`.
- `requirements.txt` (pinned; fully local — no LLM client).
- `README.md` quick-start skeleton.

**Verification**
- Ran `app.startup.run_startup()` locally: created all dirs, emitted the structured
  startup audit event, wrote `logs/audit.log.jsonl`. ✅
- Verified config validation rejects bad input (e.g. `CHUNK_OVERLAP >= CHUNK_SIZE`)
  with a clear `ConfigError`. ✅
- (Docker build not run in this environment; compose/Dockerfile authored to spec.)

**Files added** — see list above (everything outside `docs/`).

**Decisions / tradeoffs**
- Model caches redirected into `data/model_cache/` via env (`HF_HOME` etc.) so the
  read-only rootfs doesn't break sentence-transformers. Documented in security model.
- `.env` auto-created by the start scripts so a non-technical user truly runs one step.

**Remaining next (Phase 2)**
- `app/security/file_policy.py`: path confinement + extension/size checks.
- Upload UI in `main.py`; persist into `data/uploads/`; audit each upload.
- `tests/test_file_policy.py`: traversal/symlink/oversize rejection.

**Risks / blockers** — none. To validate the read-only-rootfs cache redirect end to
end, a real `docker compose up` is needed (not available in this authoring env).

## Phase 2 — Document upload + safe storage boundary  ✅ (2026-06-22)

**Completed**
- `app/security/file_policy.py` — the filesystem boundary:
  - `sanitize_filename` — basename-only, unicode-normalized, control/metachar
    stripped, guaranteed non-empty.
  - `ensure_within_data_dir` — resolves realpath and asserts containment in
    `DATA_DIR` (rejects `..`, absolute paths, symlink escapes, cross-drive).
  - `validate_upload` — extension allow-list + size limit + empty-file rejection.
  - `store_upload` — writes via `O_CREAT|O_EXCL|O_NOFOLLOW`, mode `0o600`, with a
    final containment assertion and collision de-duplication; returns metadata
    incl. sha256.
  - `list_upload_files` — read-only, boundary-checked listing.
- `app/main.py` — upload UI: multi-file uploader (restricted to allowed types),
  per-file validation, success/error feedback, stored-documents table. Rerun-safe
  via a session-level dedupe set. Emits `upload_stored` / `upload_rejected` audit
  events.
- `tests/test_file_policy.py` — 21 tests covering sanitization, traversal,
  symlink escape, absolute paths, disallowed extensions, oversize, empty, dedupe,
  and listing.
- `requirements-dev.txt` — pinned pytest for the test suite.

**Verification**
- `pytest tests/test_file_policy.py` → **21 passed**. ✅ (run in a throwaway venv;
  test artifacts and venv cleaned up afterward.)

**Files added/changed**
- Added: `app/security/file_policy.py`, `tests/test_file_policy.py`,
  `requirements-dev.txt`.
- Changed: `app/main.py` (upload UI + audit), `docs/security_model.md` (§3 + change
  log).

**Decisions / tradeoffs**
- Used low-level `os.open` with `O_EXCL|O_NOFOLLOW` instead of `open()` so a planted
  symlink at the target path cannot be followed — stronger than a pre-write `exists()`
  check alone.
- Session-level upload dedupe (keyed by name+size) avoids Streamlit reruns
  re-storing the same file.

**Remaining next (Phase 3)**
- `rag/loaders.py` (txt/md/pdf), `rag/splitter.py` (chunking),
  `rag/embeddings.py` (local sentence-transformers), `rag/vector_store.py`
  (ChromaDB persistence + metadata). Index on upload.

**Risks / blockers** — none. Phase 3 introduces the first heavy deps
(sentence-transformers/chromadb); they aren't import-tested in this authoring env but
are pinned and exercised at container build / first run.

## Phase 3 — Chunking + embeddings + vector store  ✅ (2026-06-22)

**Completed**
- `app/rag/loaders.py` — txt/md (UTF-8, lenient) + pdf (pypdf, per-page tolerant,
  no embedded-content execution). Enforces the filesystem boundary before reading;
  rejects unsupported types and empty/image-only extraction.
- `app/rag/splitter.py` — dependency-free overlapping chunker: normalize → split on
  paragraphs → pack into `chunk_size` windows with `chunk_overlap` carry-over;
  hard-wraps over-long paragraphs. Returns indexed `Chunk`s.
- `app/rag/embeddings.py` — local sentence-transformers wrapper; lazy, thread-safe,
  memoized; model cached in the writable volume; normalized vectors; **no network /
  no credentials**.
- `app/rag/vector_store.py` — persistent ChromaDB wrapper (cosine, telemetry off).
  Embeddings computed by us and passed in (Chroma never calls out). Idempotent
  indexing keyed by content hash (`doc_hash:chunk_index` ids, upsert). `query`,
  `document_exists`, `stats` helpers.
- `app/main.py` — index-on-upload: after a file is stored it is loaded, chunked,
  embedded, and indexed (with a spinner). Emits `index_completed` / `index_failed`
  audit events; document list now shows index stats (docs + chunks).
- `tests/test_rag_text.py` — 8 tests for loaders + splitter (boundary enforcement,
  empty/unsupported, multi-chunk indices, hard-wrap).

**Verification**
- `pytest tests/test_rag_text.py tests/test_file_policy.py` → **29 passed**. ✅
- AST-parsed all RAG modules + `main.py` (heavy ML deps load at container runtime,
  not in this authoring env). ✅

**Files added/changed**
- Added: `app/rag/{loaders,splitter,embeddings,vector_store}.py`,
  `tests/test_rag_text.py`.
- Changed: `app/main.py` (index-on-upload + stats display).

**Decisions / tradeoffs**
- We compute embeddings ourselves and hand them to Chroma (rather than letting Chroma
  pick an embedding function) to *guarantee* nothing reaches a remote API — reinforces
  the no-egress property.
- Idempotency keyed by SHA-256 content hash: re-uploading identical content is a
  no-op, and chunk ids are deterministic so re-index upserts instead of duplicating.
- Tests split into a fast, dep-free suite; embedding/Chroma behavior is validated on
  first real container run.

**Remaining next (Phase 4)**
- `rag/retriever.py` (embed query → top-k), `rag/qa.py` (extractive grounded
  answer + citations), question UI + sources panel in `main.py`.

**Risks / blockers** — first real `docker compose up` will download the embedding
model once (~80 MB) into `data/model_cache/`; documented in README.

## Phase 4 — Retrieval + Q&A loop  ✅ (2026-06-22)

**Completed**
- `app/rag/retriever.py` — embed the question locally → top-k nearest chunks from
  the vector store. No FS/network/generation; returns `{text, stored_name,
  chunk_index, score}`.
- `app/rag/qa.py` — **extractive** grounded answering: filters retrieved chunks by a
  minimum similarity (`_MIN_SCORE = 0.20`), composes an attributed answer from the
  strongest passages, and marks `grounded=False` (with a helpful message) when
  nothing relevant is found. Deliberately no LLM — honest for a local zero-cred demo
  and narrows the prompt-injection surface.
- `app/main.py` — two-column layout: a **question box + answer + expandable sources**
  panel on the left, upload/list on the right. Emits `question_asked` / `qa_failed`
  audit events (with per-source name+score, no secrets).
- `tests/test_qa.py` — 4 tests (empty question, grounded-with-sources, ungrounded
  below threshold, snippet truncation), retriever monkeypatched to stay offline.

**Verification**
- `pytest tests/` → **33 passed** (21 file_policy + 8 rag_text + 4 qa). ✅
- All Phase 4 modules AST-parse. ✅
- E2E flow (upload→index→ask→answer+sources) exercised at the unit level; the live
  embedding/Chroma path runs on first container start.

**Files added/changed**
- Added: `app/rag/retriever.py`, `app/rag/qa.py`, `tests/test_qa.py`.
- Changed: `app/main.py` (Q&A UI + sources panel + audit).

**Decisions / tradeoffs**
- Kept answering **extractive** (compose + cite top chunks) rather than adding a
  local generative LLM in V1: matches the user's "fully local only" decision, avoids
  a large model dependency, and is the safer default against injection. LLM answering
  is the headline future extension.
- Minimum-relevance threshold prevents confidently presenting unrelated chunks as an
  "answer"; weak retrievals are still shown transparently under Sources.

**Remaining next (Phase 5)**
- `app/tools/{allowed_tools,document_tools}.py`: explicit capability registry
  exposing ONLY `list_documents` + `retrieve_chunks`; route UI calls through it;
  deny-by-default dispatcher; tests.

**Risks / blockers** — none.

## Phase 5 — Explicit tool / capability boundary  ✅ (2026-06-22)

**Completed**
- `app/tools/document_tools.py` — the two concrete, read-only capabilities:
  `list_documents` (names+sizes+index stats, no path input) and `retrieve_chunks`
  (query + optional `top_k`, validated, no path input).
- `app/tools/allowed_tools.py` — the **deny-by-default allow-list**:
  - frozen `Tool` registry containing exactly `list_documents` + `retrieve_chunks`,
    each with a JSON-schema param description (ready for future LLM tool-use).
  - `call_tool(name, cfg, **kwargs)` dispatcher: rejects unknown tool names
    (`ToolNotAllowedError`), rejects unexpected params per-tool (`ToolExecutionError`),
    caps `retrieve_chunks.top_k` at 20, and audits every call
    (`tool_invoked`/`tool_denied`/`tool_error`).
  - `available_tools()` exposes public descriptions only (no callables leak).
- **Routed the app through the boundary:** `rag/qa.py` now retrieves via
  `call_tool("retrieve_chunks", …)`; `main.py` document list + ask-gating go via
  `call_tool("list_documents", …)`. The sidebar now lists the allowed capabilities
  and states that anything else is denied.
- `tests/test_allowed_tools.py` — 11 tests: exact-registry, no-callable-leak,
  unknown-tool denial (parametrized), unexpected-param rejection, query validation,
  and dispatch for both tools.
- Updated `tests/test_qa.py` to patch the boundary call (`qa.call_tool`).

**Verification**
- `pytest tests/` → **44 passed** (21 file_policy + 8 rag_text + 4 qa + 11 tools). ✅
- All refactored modules AST-parse. ✅

**Files added/changed**
- Added: `app/tools/document_tools.py`, `app/tools/allowed_tools.py`,
  `tests/test_allowed_tools.py`.
- Changed: `app/rag/qa.py` (retrieve via boundary), `app/main.py` (list via boundary
  + capabilities panel), `tests/test_qa.py`, `docs/security_model.md` (§4 + change log).

**Decisions / tradeoffs**
- Made `call_tool` the single dispatch path for *both* the current UI and any future
  LLM agent, so the same allow-list governs everything — the boundary isn't bypassable
  by the app itself.
- Added per-tool parameter allow-listing (not just name allow-listing) so a caller
  can't smuggle an unexpected argument into a tool.

**Remaining next (Phase 6)**
- Logging polish (ensure all events consistent), env-validation messaging, start-script
  polish, README architecture section, optional `docs/setup_flow.md` + threat model.

**Risks / blockers** — none.

## Phase 6 — Logging + setup polish + security writeup  ✅ (2026-06-22)

**Completed**
- **Logging** — confirmed the structured audit event inventory is consistent across
  the app: `app_startup`, `upload_stored`/`upload_rejected`,
  `index_completed`/`index_failed`, `question_asked`/`qa_failed`,
  `tool_invoked`/`tool_denied`/`tool_error`. Documented the full list (+ redaction)
  in the README.
- **Setup polish** — `start.sh`/`start.bat` now also verify the **Docker daemon is
  running** (not just installed), the most common non-technical failure, with an
  actionable message before any build is attempted.
- **README** — added Architecture diagram + component table, "Security at a glance",
  audit-event list, configuration table, and a Tests section.
- **Docs** — added `docs/setup_flow.md` (exact one-command flow, first-run vs repeat,
  reset) and `docs/threat_model.md` (assets, actors/trust boundaries, STRIDE-lite
  threats+mitigations, explicitly-accepted risks).
- Fixed the stale `app/main.py` module docstring.

**Verification**
- `pytest tests/` → **44 passed**. ✅
- `bash -n scripts/start.sh` → syntax OK; `main.py` AST-parses. ✅

**Files added/changed**
- Added: `docs/setup_flow.md`, `docs/threat_model.md`.
- Changed: `app/main.py` (docstring), `scripts/start.sh`, `scripts/start.bat`,
  `README.md`.

**Decisions / tradeoffs**
- Kept extractive answering and the no-LLM posture from Phase 4 (consistent with the
  fully-local decision); threat model frames prompt injection as reduced-but-present
  and an explicit future item rather than claiming it's solved.

**Remaining next (Phase 7)**
- Final pass: cross-check docs vs. code, confirm E2E runnability story, ensure the
  repo is clean, write the closing status + limitations/future-work summary.

**Risks / blockers** — none.

## Phase 7 — Review / cleanup / final documentation  ✅ (2026-06-22)

**Completed**
- Ran two **parallel review audits** (code correctness/security + docs-vs-code
  consistency):
  - Security verdict: filesystem boundary and capability allow-list are solid; all 7
    container hardening controls present; all 10 audit events real; "fully local / no
    credentials" confirmed (no API client in code or `requirements.txt`).
  - Found & fixed: README config table was missing `DATA_DIR`/`LOG_DIR`/`APP_ENV`
    (added); simplified the redaction regex to exactly the documented patterns
    (dropped redundant `API_KEY` alternative already covered by `_KEY$`).
- **Robustness fix:** Q&A and indexing now also catch `EmbeddingError` (and Q&A
  catches `ToolExecutionError`), so a model/index failure shows a friendly message
  instead of a Streamlit stack trace. Audited via `qa_failed` / `index_failed`.
- Added `tests/test_logger_redaction.py` (3 tests) covering documented redaction
  patterns + nested structures.
- Repo cleanup: removed stray `.pytest_cache`/pycache; runtime dirs hold only
  `.gitkeep`; added `data/model_cache/.gitkeep`.

**Verification**
- `pytest tests/` → **47 passed** (21 file_policy + 8 rag_text + 4 qa + 11 tools + 3
  redaction). ✅
- Redaction sanity-checked directly; `main.py` AST-parses; `start.sh` bash-syntax OK.

**Files added/changed**
- Added: `tests/test_logger_redaction.py`.
- Changed: `app/main.py` (broader Q&A/index error handling), `app/logger.py` (regex
  + comment), `README.md` (config table), `docs/implementation_plan.md` (status +
  change log), this file.

**Final V1 deliverables checklist**
- ✅ Runnable, Dockerized, one-command setup (`docker compose up --build` / start
  scripts with Docker-daemon check).
- ✅ Document upload + Q&A with source display (fully local, extractive).
- ✅ Explicit deny-by-default tool/capability boundary (2 tools).
- ✅ Restricted filesystem (tested), scoped secrets (none needed), structured audit
  logging.
- ✅ Hardened container (non-root, read-only rootfs, cap_drop ALL,
  no-new-privileges, noexec tmpfs, resource limits).
- ✅ Docs: `implementation_plan.md`, `progress_log.md`, `security_model.md`,
  `setup_flow.md`, `threat_model.md`, `README.md`.
- ✅ 47 unit tests passing.

**Known limitations (carried forward, documented):** no auth, prompt injection not
fully mitigated, single-tenant, Docker-default syscall filtering, deps not hash-pinned.
See `security_model.md` §8 and `threat_model.md` §4.

**Risks / blockers** — none. One environmental note: the heavy ML deps
(sentence-transformers, chromadb) and the embedding-model download exercise on the
first real `docker compose up`; all pure-Python logic is unit-tested here.

## Post-V1 fix — CPU-only torch  (2026-06-22)

**Issue:** First `docker compose up --build` pulled the **CUDA build of torch**
(~426 MB) plus ~1.5 GB of NVIDIA CUDA/cuDNN wheels — unused, since the app does
CPU-only embeddings in a GPU-less `aarch64` container. Build hung for 500+ s on the
pip step.

**Fix:** `requirements.txt` now pins `torch==2.5.1` from PyTorch's CPU wheel index
(`--extra-index-url https://download.pytorch.org/whl/cpu`), placed before
`sentence-transformers` so the CPU build resolves first. No Dockerfile change needed
(pip honors the in-file index directive). Net effect: ~2 GB → ~200 MB of torch deps,
much faster build, smaller image.

**Security note:** documented the added (official, trusted) package index in
`threat_model.md` §4; `torch` is version-pinned so the wider index doesn't enable
substitution.

**Files changed:** `requirements.txt`, `docs/threat_model.md`, this file.

## Post-V1 fix — `ModuleNotFoundError: No module named 'app'`  (2026-06-22)

**Issue:** Container started but Streamlit crashed at `from app.logger import audit`.
Streamlit runs `app/main.py` as a script, so `sys.path[0]` is `/app/app` (the file's
dir), not `/app` — the top-level `app` package wasn't importable.

**Fix (two layers):**
- `Dockerfile`: added `PYTHONPATH=/app` to the `ENV` block.
- `app/main.py`: added a path-bootstrap at the top that inserts the project root into
  `sys.path` before any `app.*` import — works regardless of launch method (covers
  local `streamlit run app/main.py` too).

**Verification:** simulated the Streamlit launch path (sys.path[0]=app/) and confirmed
`app.*` imports resolve; `pytest` → **47 passed**.

**Files changed:** `Dockerfile`, `app/main.py`, this file.

## Post-V1 fix — Ask panel not unlocking after first upload  (2026-06-22)

**Issue:** After uploading + successfully indexing a doc (e.g. README.md → 12
chunks), the left "Ask your documents" panel stayed gated on "Upload a document
first…". Cause: `_render_ask` (left column) renders *before* `_render_upload` (right
column) does the indexing in the same script pass, so the gate's chunk-count check
read 0; with no further interaction, Streamlit didn't rerun to refresh it.

**Fix:** `_index_stored` now returns whether new chunks were indexed; the upload
handler calls `st.rerun()` once after a successful new index, so the page
re-evaluates and the Ask box appears with the correct index state.

**Verification:** `main.py` parses; `pytest` → **47 passed**.

**Files changed:** `app/main.py`, this file.

## V1 sign-off — verified running end-to-end  (2026-06-22)

Confirmed live on Apple Silicon + Docker: upload README.md → 12 chunks indexed →
question → extractive grounded answer with cited README passages + relevance scores.
All security boundaries intact during the real run. User reviewed the extractive
answer style and chose to **stop at V1** (keep it fully-local / no-LLM as designed).

Build/runtime issues found and fixed during bring-up (all logged above):
1. CUDA torch bloat → CPU-only `torch==2.5.1` via PyTorch CPU index.
2. Dockerfile pip-layer cache invalidation → reordered `ENV PYTHONPATH` after the
   pip layer.
3. `ModuleNotFoundError: app` → `PYTHONPATH=/app` + in-file sys.path bootstrap.
4. Ask panel not unlocking after first upload → `st.rerun()` after a new index.

**V1 is closed.** Any further work (extractive tuning, local/API LLM answering, auth)
is a new milestone.

<!-- V1 complete. New milestones (e.g. LLM answering, auth) would start a new section. -->
