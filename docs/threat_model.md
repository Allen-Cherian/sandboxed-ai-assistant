# Threat Model

A lightweight threat model for the Minimal Sandboxed AI Assistant. It states what we
defend against, what we explicitly do **not**, and why — so the security claims are
honest and scoped. Pairs with `security_model.md` (the controls) — this doc is the
*reasoning*.

Covers the default (extractive, fully-local) build **and** the optional local-LLM mode
(`LLM_ENABLED`, off by default). Rows that change between the two are called out.

---

## 1. Assets

| Asset | Why it matters |
|-------|----------------|
| Uploaded documents | May contain the user's private/sensitive content. |
| Vector index (`chroma/`) | Derived from documents; same sensitivity. |
| Audit logs | Integrity matters for accountability; must not contain secrets. |
| The host system | Must be protected from a compromised app/container. |
| Configuration / any future secret | Must never leak into images or logs. |

---

## 2. Actors / trust boundaries

| Actor | Trust level | Notes |
|-------|-------------|-------|
| Operator (runs the container) | **Trusted** | Owns the host and config. |
| End user (uploads / asks) | **Semi-trusted** | May supply hostile filenames or document content. |
| Uploaded document content | **Untrusted data** | Could attempt traversal (via name) or injection (via text). |
| External network | **Out of scope** | V1 makes no outbound calls; nothing to attack here. |

Primary trust boundary: **host ↔ container**, enforced by Docker hardening. Secondary:
**app ↔ documents/tools**, enforced by `file_policy` and the tool allow-list.

---

## 3. Threats considered (STRIDE-lite) and mitigations

| Threat | Vector | Mitigation (V1) | Residual |
|--------|--------|-----------------|----------|
| **Path traversal / FS escape** | Hostile upload filename (`../`, abs path, symlink) | `file_policy`: basename sanitize + realpath containment + `O_NOFOLLOW` write; tested. | Low. |
| **Malicious file type / oversize** | Disallowed extension, huge file (DoS) | Extension allow-list + size cap + empty-file reject. | Low. |
| **Container escape / host tampering** | App compromise tries to write host/code | Non-root, read-only rootfs, `cap_drop: ALL`, `no-new-privileges`, noexec tmpfs, single writable volume. | Medium (Docker-default syscall filtering only — see §4). |
| **Excess capability / confused deputy** | App/agent tries an action beyond Q&A | Deny-by-default tool allow-list (only `list_documents`, `retrieve_chunks`); no shell/eval/FS/network primitives; per-param allow-listing. | Low. |
| **Secret leakage** | Secret in image, log, or repo | Env-only config; `.env` git/docker-ignored; log redaction; **no secret required in V1**. | Low. |
| **Resource exhaustion (DoS)** | Large/many uploads, huge `top_k`, slow/runaway LLM | Size limit, `top_k` capped at 20, container cpu/mem limits; LLM call has a hard timeout + response-size cap. | Medium (no per-user rate limiting). |
| **Data exfiltration to third parties** | Sending docs to an external API | Default + LLM-mode (local Ollama): **no data leaves the machine**. Only a future cloud API provider (opt-in, off by default) would send text off-machine — re-documented at that time. | Very low (default); by-design opt-in (cloud provider). |
| **Prompt injection (LLM mode)** | Malicious document text steering the model | Untrusted-data system prompt + `BEGIN/END CONTEXT` delimiting + **LLM has no tools** (injection can alter text, not cause actions) + sources shown; grounding gate (no chunks → no LLM call). | Medium — reduced, not eliminated. |
| **Tampered audit trail** | Hide actions by editing logs | Append-only JSON lines; logs on a host-visible volume. | Medium (no signing/WORM). |

---

## 4. Explicitly NOT defended against in V1 (accepted risk)

| Not defended | Why it's acceptable for V1 | Future direction |
|--------------|----------------------------|------------------|
| **Full prompt-injection defense** | Extractive mode quotes chunks; LLM mode (opt-in) adds an untrusted-data prompt + delimiting + a no-tools constraint, so injection can at most alter answer text, not cause actions. Basic, not comprehensive. | Add injection classifiers / output filtering; keep the LLM tool-less. |
| **No authentication** | Single-user local demo on `localhost`. | Add auth / per-user isolation for multi-user. |
| **Malicious operator** | The operator is trusted by definition (owns the host). | Out of scope. |
| **Kernel/syscall-level attacks** | Relies on Docker defaults; no custom seccomp/AppArmor/gVisor. | Author seccomp/AppArmor profiles; consider gVisor. |
| **Supply-chain compromise** of deps | Deps are version-pinned but not hash-pinned; no SBOM. `requirements.txt` adds PyTorch's official CPU wheel index (`download.pytorch.org`) via `--extra-index-url` to avoid pulling ~2 GB of unused CUDA wheels — a second (official, trusted) package source. `torch` is version-pinned, so the wider index does not enable surprise substitution. | Hash-pin, generate SBOM, scan; consider a vendored/private mirror. |
| **Log integrity / WORM** | Local demo. | Ship to append-only/remote sink; sign entries. |

---

## 5. Summary

V1's strongest properties are **no outbound network / no credentials** (removing a
whole class of exfiltration and secret-leak risks), a **tested filesystem boundary**,
and a **deny-by-default capability surface**. The honestly-accepted gaps are prompt
injection, authentication, and kernel-level hardening — all listed here and in
`security_model.md` §8, and all positioned as the natural next increments rather than
hidden assumptions.
