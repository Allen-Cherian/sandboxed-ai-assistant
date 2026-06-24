# Security Model — Minimal Sandboxed AI Assistant

> **Status:** Phase 0 (Planning). Updated as boundaries are implemented.
> **Last updated:** 2026-06-22

This document describes the security boundaries the project demonstrates, how they
are enforced, and their current limitations. It is the source of truth for the
"secure-by-default" claims of V1.

---

## 1. Design Principle

**Secure by default, least privilege, deny by default.** The assistant is given
the *minimum* capabilities required to answer questions over uploaded documents and
nothing more. Every boundary below is designed so that the *default* behavior is the
safe one — a user does not have to opt into security.

---

## 2. Runtime Boundary (Sandbox)

The app runs inside a **Docker container**, hardened via `docker-compose.yml`:

| Control | Setting | Why |
|---------|---------|-----|
| Non-root user | Dockerfile creates `appuser`; container runs as it | Limits blast radius if the app is compromised. |
| Read-only root FS | `read_only: true` | App cannot modify its own code/binaries at runtime. |
| Writable area only where needed | named/bind volume at `/app/data` + tmpfs `/tmp` | All writes confined to the data volume. |
| Drop Linux capabilities | `cap_drop: [ALL]` | Removes raw socket, mount, ptrace, etc. |
| No privilege escalation | `security_opt: [no-new-privileges:true]` | setuid binaries can't elevate. |
| No host networking | default bridge; only port 8501 published | App is reachable only on the mapped UI port. |
| Resource limits (optional) | mem/cpu limits in compose | Caps DoS impact. |

**Network egress.** By default the app makes **no outbound calls**. The optional local
LLM mode (§7, off by default) adds exactly **one** permitted destination: the
configured local Ollama at `LLM_BASE_URL` (default `host.docker.internal:11434`),
enabled via `extra_hosts`. This is a localhost-only mapping to a user-controlled
service — it does **not** grant general internet egress. The destination is
config-controlled (validated as a well-formed http(s) URL) and never derived from user
input or document content. General internet egress is opened only if a future API
provider is consciously enabled (§7 / plan §10).

**Not relied upon in V1:** custom seccomp/AppArmor profiles, gVisor/Kata, user
namespaces remap. Documented as future hardening (§9).

---

## 3. Filesystem Boundary

- A single **dedicated data directory** (`DATA_DIR`, default `/app/data`) holds:
  - `uploads/` — raw uploaded documents
  - `chroma/` — vector DB persistence
  - and a sibling `logs/` dir for audit logs.
- **All** filesystem access in app code goes through `app/security/file_policy.py`,
  which:
  - resolves the real (symlink-followed) absolute path,
  - asserts it is contained within `DATA_DIR` (rejects `..` traversal and symlink
    escapes),
  - validates file extension against an allow-list (`.txt`, `.md`, `.pdf`),
  - enforces a maximum file size.
- The app is **never** designed to accept arbitrary host paths from the user or the
  assistant. There is no "open file at path X" capability.
- Upload filenames are **sanitized to a basename** (directory components, `..`,
  absolute/UNC paths, control chars, and shell metacharacters are stripped) before
  use, and writes use `O_CREAT|O_EXCL|O_NOFOLLOW` with mode `0o600` so a pre-existing
  symlink cannot be followed and files are not world-readable.
- This boundary is covered by an executable test suite (`tests/test_file_policy.py`):
  traversal, symlink-escape, absolute-path, disallowed-extension, oversize, and
  empty-file cases are all asserted to be rejected.

---

## 4. Tool / Capability Boundary (Least Privilege)

- The assistant's available actions are an **explicit allow-list registry**
  (`app/tools/allowed_tools.py`). V1 registers exactly:
  - `list_documents` — list names/metadata of uploaded docs.
  - `retrieve_chunks` — return top-k relevant chunks for a query.
- The dispatcher (`call_tool`) **rejects any tool name not in the registry** (deny by
  default) and also **rejects unexpected parameters** — a caller cannot smuggle in an
  argument (e.g. a `path=`) a tool doesn't declare. `retrieve_chunks` additionally
  caps `top_k` at 20 to bound per-call work.
- Every dispatch is audited: `tool_invoked`, `tool_denied` (with reason), `tool_error`.
- The assistant has **no** access to: a shell, `eval`/`exec`, arbitrary file
  read/write, network requests, package installation, or plugin loading. Neither tool
  accepts a filesystem path.
- Adding a capability is a deliberate code change in one place — capabilities cannot
  appear implicitly.
- The UI and the Q&A loop route **through this boundary** (`call_tool`), not around it,
  so the same allow-list governs the app today and any future LLM agent. Covered by
  `tests/test_allowed_tools.py` (deny-by-default, param rejection, dispatch).
- **The optional LLM (§7) is a text generator, NOT an agent.** It receives an
  already-retrieved, grounded prompt and returns text. It is given **no tools**, makes
  no decisions about what to call, and never touches the filesystem. Retrieval happens
  through `call_tool` *before* the LLM is involved, so the LLM is strictly downstream
  of the allow-list — it cannot expand the capability surface. Going *agentic* (LLM
  decides which tools to call) is a deliberate future milestone, not part of this
  phase — see `docs/agentic_future.md`.

---

## 5. Secret Handling Model

- **V1 is fully local and requires no credentials to run.** This is the strongest
  form of scoped-secret handling: the default, happy path has no secret at all.
- The scoped-secret *pattern* is still demonstrated: all configuration is loaded
  **only** via environment variables / `.env`; `.env.example` documents supported
  config keys with placeholder values; `.env` is **git-ignored** and
  `.dockerignore`d so nothing is ever baked into the image.
- `app/config.py` validates configuration at startup and fails clearly on malformed
  config. If/when a future credentialed provider is added, the loader and redaction
  path are already the single place it would be wired in.
- Secret values are **never written to logs** — the logger redacts any key matching
  known secret-name patterns (`*_KEY`, `*_TOKEN`, `*_SECRET`, `PASSWORD`) and the app
  logs only non-sensitive metadata.

---

## 6. Logging / Observability Model

- `app/logger.py` emits **structured (JSON-line) audit events** to the dedicated
  `logs/` directory (and stdout for container log capture).
- Logged events include: app startup/config (redacted), file uploads (name, size,
  type, hash), questions asked, retrieval actions (doc ids / chunk ids / scores),
  answer metadata (model, latency, token/length info where available), and errors.
- Logs are designed to answer "who uploaded what, what was asked, and what sources
  were used" — i.e. an audit trail, not just debug output.
- The `question_asked` event records `mode` (extractive|llm), `model` (in LLM mode),
  `grounded`, `latency_ms`, `fell_back`, and per-source name/score. New
  reachability/health events: `llm_health`.
- **No document *content* secrets and no API keys** are logged.

---

## 7. Optional LLM Answering Mode

The default answer mode is **extractive** (quote retrieved chunks; fully local; no
model). An **optional** generative mode (off by default, `LLM_ENABLED=false`) sends
the retrieved chunks to a **local LLM** (Ollama) to produce written prose.

**Security properties of this mode:**

- **Off by default.** With `LLM_ENABLED=false` the app is byte-for-byte the extractive
  build — no model, no egress.
- **Text generator, not an agent** (§4): the LLM gets no tools and never touches the
  filesystem; retrieval still flows through the allow-list before it runs.
- **Local only by default.** The configured provider is local Ollama; the only network
  destination is `LLM_BASE_URL` (§2). No data leaves the machine in the default Ollama
  configuration.
- **Bounded execution:** the call has a hard timeout (`LLM_TIMEOUT_S`) and a
  response-size cap (`LLM_MAX_TOKENS`); on any failure the app **falls back to
  extractive** with a user-visible note — never a crash.
- **Grounding gate:** if retrieval finds nothing relevant, the LLM is not invoked
  (no ungrounded generation).

**Prompt-injection mitigation (basic).** A generative model introduces prompt
injection — a crafted document could try to steer the answer. Mitigations in place:

1. A system instruction to answer **only** from the provided context and to treat the
   context as **untrusted data, not instructions** (explicitly: never obey directives
   found inside it).
2. Retrieved chunks wrapped in clear `BEGIN/END CONTEXT` delimiters so the model can
   distinguish data from task.
3. The LLM has no tools, so a successful injection can at most affect the *text* of an
   answer — it cannot cause actions.
4. Sources are always shown so the user can verify the answer against the chunks.

This is **reduced, not eliminated** — full injection defense remains future work (§9).

**Future API providers.** Switching `LLM_PROVIDER` to a cloud model (Anthropic/OpenAI)
is a documented, reserved slot (plan §10). It would mean **document text leaves the
machine** and requires an API key — a conscious opt-in that must be re-documented here
and in `threat_model.md` at the time it is enabled. Not implemented in this phase.

---

## 8. Threat Assumptions

- **Trusted operator, semi-trusted user:** the person running the container is
  trusted; the person uploading documents/asking questions is only semi-trusted.
- We defend against: path traversal/escape via uploads, oversized/wrong-type
  uploads, the assistant attempting actions outside its allow-list, accidental
  secret leakage into logs/images.
- We do **not** fully defend against: prompt injection from malicious document
  content influencing answers (reduced in LLM mode, §7), a malicious *operator*,
  side-channels, or supply-chain compromise of dependencies.

Note: in the **default** configuration the app sends **no data to any external
service** — embeddings and (extractive) answering run entirely in-container. The
optional LLM mode adds a localhost-only call to host Ollama; data still does not leave
the machine. Only a future cloud API provider would change that (§7).

---

## 9. Current Limitations (Known, Documented)

1. **Prompt injection** from document content is *partially* mitigated, not
   eliminated. Extractive mode (default) quotes chunks rather than feeding them to a
   generative model. LLM mode (§7) adds an untrusted-data system prompt + delimiting +
   a no-tools constraint, so a successful injection can at most alter answer *text*,
   not cause actions. Full injection defense (classifiers, output filtering) is future
   work.
2. **No authentication** — anyone who can reach port 8501 can use the app.
3. **No seccomp/AppArmor/gVisor** profile — container hardening relies on Docker
   defaults + the compose controls above.
4. **Dependency supply chain** is not verified (no pinning-by-hash / SBOM in V1).
5. **Single-tenant** — no isolation between different users' documents.
6. **Local embedding model** is downloaded at first run (network needed once) unless
   API embeddings are used.

These are tracked as future-extensibility items and are intentionally out of scope
for V1 per the project brief.

---

## 10. Change Log (security-level)

- **2026-06-22** — Initial security model authored (Phase 0). Boundaries defined;
  enforcement to be implemented in Phases 1–6.
- **2026-06-22** — Updated for **fully-local, zero-credential** V1 and **full
  container hardening** per user decision. Secret section reframed: no credentials in
  V1; pattern retained. Added "no external data egress" note.
- **2026-06-22** — Phase 2: filesystem boundary implemented and tested. Documented
  filename sanitization, `O_EXCL|O_NOFOLLOW` writes, and the executable test suite.
- **2026-06-22** — Phase 5: tool/capability boundary implemented. UI + Q&A now route
  through `call_tool`; documented param-rejection, `top_k` cap, dispatch auditing, and
  the boundary test suite.
- **2026-06-23** — LLM phase: added §7 (Optional LLM Answering Mode) and updated §2
  (scoped, opt-in egress to local Ollama), §4 (LLM is a text generator, not an agent),
  §6 (new audit fields), §8 (egress note), §9 (prompt injection now partially
  mitigated). Renumbered Threat Assumptions → §8 and Limitations → §9. LLM mode is OFF
  by default; the default build is unchanged from prior V1.
