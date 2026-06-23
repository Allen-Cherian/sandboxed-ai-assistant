# Agentic & Multi-Agent — Clarification and Future Path

> **Status:** Documentation only. **Not implemented and not planned for the current
> LLM phase.** This captures the design reasoning so a future agentic milestone starts
> from a clear, honest baseline.
> **Last updated:** 2026-06-23

This doc answers a recurring question: *"We have a single assistant now — what if we
want to add more agents and let the LLM make decisions?"* The short version: it's
**possible and the foundation supports it**, but it's a **fundamental architectural
shift**, not an increment — and it's where security gets genuinely hard.

---

## 1. Important clarification: today there is no "agent"

This distinction drives everything below.

- **What the project is today (and after the LLM phase): a *pipeline*.** Code decides
  the steps in a fixed order (retrieve → answer). The LLM is a **text generator** at
  the end — text in, text out. It has no tools, no choices, no control.
- **An *agent*: an LLM that decides what to do** — which tools to call, in what order,
  when to stop. The LLM is in the driver's seat.

So "add agents / let the LLM make decisions" means moving the LLM from **passenger to
driver**. That is a different system, not a bigger version of this one.

---

## 2. The security inversion (why this is a big deal)

```
TODAY (pipeline):
   code → call_tool("retrieve_chunks") → LLM writes text
   The GATE is called by trusted CODE. The LLM is downstream, powerless.

AGENT (LLM decides):
   LLM → "call retrieve_chunks" → call_tool(...) → LLM → "now call X" → ...
   The GATE is now called by the LLM ITSELF. The LLM is upstream, in control.
```

**The critical consequence:** the thing choosing which tools to call becomes an LLM
that can be influenced by **untrusted document content (prompt injection)**.

- In the pipeline, a malicious document can at worst produce a **bad answer**.
- In an agent, a malicious document could try to make the LLM **take actions** — call
  tools it shouldn't, in sequences you never intended ("confused deputy").

This is exactly why the project's tool allow-list is not a nice-to-have: in an agentic
world it is the line between "helpful assistant" and "an LLM doing what a malicious PDF
told it to."

---

## 3. The good news: the foundation is already agent-ready

The allow-list (`app/tools/allowed_tools.py::call_tool`) **does not care who calls
it.** Today trusted code calls it; an LLM could call it tomorrow. Either way it
enforces:

- only explicitly-registered tools (deny by default),
- only declared parameters,
- per-call resource caps,
- an audit record of every call.

So the boundary that makes agents *safe* already exists. An agent built on this project
would still be **physically unable** to call a tool that isn't registered — even if a
document convinced it to try. Most agent frameworks do **not** have this property by
default; this project does.

---

## 4. What an agentic version would actually require

A separate, larger milestone — **not** the current LLM phase. Two stages:

### Stage 1 — Single agent (LLM calls tools)
- A **tool-use loop**: LLM proposes a tool call → `call_tool` executes it (gate
  unchanged) → result returns to the LLM → repeat until a final answer.
- Needs a model with **reliable structured tool-calling** (a 1–2B local model is weak
  at this; realistically a 7B+ local model or an API model — see the provider
  abstraction in `phase_llm_plan.md`).
- **Security work becomes mandatory, not optional:**
  - real prompt-injection defenses (not just the basic grounding prompt),
  - a **hard cap on tool-call iterations** (no infinite/expensive loops),
  - per-tool rate limits,
  - likely a **human-approval step** for any state-changing action.

### Stage 2 — Multiple agents
- e.g. a **Researcher** (retrieves), a **Writer** (composes), an **Orchestrator**
  (routes between them).
- **Each agent gets its OWN allow-list** — least privilege *per agent*:

```
            ┌─────────────┐
   user →   │ Orchestrator│   routes work to agents
            └──────┬──────┘
          ┌────────┴────────┐
   ┌──────▼─────┐    ┌──────▼─────┐
   │ Researcher │    │  Writer    │
   │ allow-list:│    │ allow-list:│
   │ retrieve,  │    │ (none —    │
   │ list_docs  │    │  text only)│
   └──────┬─────┘    └────────────┘
          │  every call still goes through call_tool (the same gate)
   ┌──────▼──────────────────────────────────────┐
   │  The SAME boundary already built —           │
   │  now scoped to a SUBSET per agent            │
   └──────────────────────────────────────────────┘
```

- This is where the registry design pays off: instead of one global allow-list, each
  agent receives a **subset** of it. The Writer, for instance, gets *no* document
  tools — only the text the Researcher hands it.

---

## 5. Effort vs. security weight (honest scorecard)

| Step | Effort | Security weight |
|------|--------|-----------------|
| LLM phase (planned) — LLM as text generator | Small (~1 file) | Adds prompt-injection risk; *basic* mitigation |
| Single agent — LLM calls tools | Medium | Injection becomes **critical**; needs real defenses + iteration caps + per-tool limits |
| Multi-agent — agents + orchestration | Large | Per-agent least privilege; the project's hardest security work |

---

## 6. Recommendation / decision

- **Do NOT fold agents into the upcoming LLM phase.** Keep that phase the simple, safe
  text-generator step.
- **Going agentic is a deliberate future milestone** with its own plan — which is
  exactly where the original brief placed *multi-agent orchestration*: **out of scope
  for V1**, for good reason.
- The architecture is intentionally **agent-ready** (the allow-list is the proof), so
  this can be picked up later without rework to the boundary — only additions
  (tool-use loop, per-agent allow-lists, injection defenses, iteration caps).

**Bottom line:** the project was built so that agents are *possible but deliberate*.
When the time comes, start from §4 here and write a dedicated milestone plan before any
code.
