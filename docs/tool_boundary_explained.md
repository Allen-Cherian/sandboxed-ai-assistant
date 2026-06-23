# Tool Boundary, Explained (Code Walkthrough)

A plain-English, line-level walkthrough of how the least-privilege tool/capability
boundary is wired in code. This is the companion to `security_model.md` §4 (which
states the *policy*); this doc shows the *mechanism*.

The boundary lives in two files:
- `app/tools/allowed_tools.py` — **the gate** (decides what is allowed)
- `app/tools/document_tools.py` — **the capabilities** (the two functions themselves)

---

## The core idea

The assistant's entire ability to act is an **explicit allow-list of exactly two
read-only functions**. Anything not on the list does not exist as far as the
assistant is concerned. The design is **deny-by-default**: refuse unless explicitly
permitted. Adding a capability requires a deliberate edit in one place — it can never
appear implicitly, via config, or via user input.

```
Caller (UI today, LLM agent later)
   │  call_tool("name", cfg, **args)
   ▼
┌──────────────────────────────────────────────┐
│ allowed_tools.py — THE GATE                  │
│  ① name on the 2-item allow-list? no → DENY  │
│  ② only declared args passed?     no → DENY  │
│  ③ audit("tool_invoked")                     │
│  ④ run the function, safely                  │
└──────────────────────────────────────────────┘
   ▼
┌──────────────────────────────────────────────┐
│ document_tools.py — THE CAPABILITY           │
│  ⑤ validate own input                        │
│  ⑥ cap own workload (anti-DoS)               │
│  ⑦ read-only; takes NO filesystem path       │
└──────────────────────────────────────────────┘
   ▼
result (data only) — or a clean, logged error
```

---

## Part A — The gate (`allowed_tools.py`)

### A.1 What a "tool" is

```python
@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    func: Callable[..., dict]   # the actual function to run
    parameters: dict            # what inputs it accepts
```

A `Tool` is a labeled, **immutable** (`frozen=True`) box holding its name, a
description, the actual callable, and a spec of its inputs. Immutability means nobody
can swap out `func` at runtime to point it at something dangerous.

### A.2 THE ALLOW-LIST itself — the heart

```python
_REGISTRY: dict[str, Tool] = {
    "list_documents":  Tool(... func=document_tools.list_documents ...),
    "retrieve_chunks": Tool(... func=document_tools.retrieve_chunks ...),
}
```

This dictionary **is** the permission list: name → the function allowed to run under
that name. There are exactly **two** entries. "Least privilege" here is not a flag —
it is this hardcoded dict. If a capability isn't a key here, it does not exist. There
is no `run_shell`, `read_file`, or `delete`, because they are not in the dict.

### A.3 The second lock — allowed parameters

```python
_ALLOWED_PARAMS: dict[str, set[str]] = {
    "list_documents": set(),               # accepts NO arguments
    "retrieve_chunks": {"query", "top_k"}, # accepts ONLY these two
}
```

Even for an allowed tool, this declares exactly which argument names it may receive.
A call like `call_tool("retrieve_chunks", cfg, query="hi", path="/etc/passwd")` is
rejected because `path` is not in the allowed set — an argument-smuggling defense.

### A.4 The gatekeeper — `call_tool` (the single door)

```python
def call_tool(name: str, cfg: Config, **kwargs) -> dict:
    tool = _REGISTRY.get(name)
    if tool is None:                                  # ① unknown tool?
        audit("tool_denied", tool=name, reason="not_in_allow_list")
        raise ToolNotAllowedError(...)

    extra = set(kwargs) - _ALLOWED_PARAMS[name]       # ② unexpected args?
    if extra:
        audit("tool_denied", ..., reason="unexpected_params", ...)
        raise ToolExecutionError(...)

    audit("tool_invoked", tool=name, params=sorted(kwargs))   # ③ log it
    try:
        result = tool.func(cfg, **kwargs)             # ④ run it safely
    except (ValueError, TypeError) as exc:
        audit("tool_error", tool=name, reason=str(exc))
        raise ToolExecutionError(...) from exc
    return result
```

Four checkpoints, in order:
1. **Name check** — not in the registry → log denial, refuse. This *is* deny-by-default.
2. **Argument check** — `set(kwargs) - allowed` finds any smuggled args → refuse.
3. **Audit** — record the invocation before running; every call leaves a trace.
4. **Safe execution** — only now call the real function, wrapped so a crash becomes a
   clean, logged error.

### A.5 The safe window — `available_tools`

```python
def available_tools() -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in _REGISTRY.values()
    ]
```

Used by the UI to display the tool list. It returns name/description/parameters but
**not `func`** — so even the display code never gets a handle to the callables.

---

## Part B — The capabilities (`document_tools.py`)

These are deliberately tiny and read-only. A limited capability *looks* limited in
code.

### B.1 `list_documents`

```python
def list_documents(cfg: Config) -> dict:
    files = list_upload_files(cfg)   # already filesystem-boundary-checked
    index = stats(cfg)               # ChromaDB counts
    return {
        "documents": [{"name": f["stored_name"], "size_bytes": f["size_bytes"]} for f in files],
        "count": len(files),
        "indexed_documents": index.get("documents", 0),
        "indexed_chunks": index.get("chunks", 0),
    }
```

- Takes **only `cfg`** — no filename, no path, no user input to redirect it.
- `list_upload_files` only ever looks inside the approved `data/uploads/` folder and
  re-checks every path (see `file_policy`), so it cannot escape the boundary.
- Returns names + sizes only — no file *contents*, no paths leaked.

### B.2 `retrieve_chunks`

```python
def retrieve_chunks(cfg: Config, *, query: str, top_k: int | None = None) -> dict:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("'query' must be a non-empty string.")
    if top_k is not None:
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("'top_k' must be a positive integer.")
        top_k = min(top_k, 20)               # hard ceiling — anti-DoS
    results = retrieve(query.strip(), cfg, top_k=top_k)
    return {"query": query.strip(), "results": results, "count": len(results)}
```

- The bare `*` forces `query`/`top_k` to be passed **by name**, never positionally —
  call sites stay explicit and predictable.
- **Input validation** — defends itself even though the gate already checked names
  (defense in depth). Invalid input → `ValueError`, which `call_tool` turns into a
  clean logged error.
- **Hard ceiling** `min(top_k, 20)` — even `top_k=1_000_000` is clamped, so the
  capability can't be abused for resource exhaustion.
- **No path parameter** — its only inputs are a text query and a number; it calls
  `retrieve(...)`, which does vector math and never touches the filesystem.

---

## How it's wired into the rest of the app

The app never calls the document functions directly — it always routes through the
gate, so the boundary is the *only* path and isn't bypassable:

```python
# rag/qa.py — retrieval goes through the gate, not a direct call
chunks = call_tool("retrieve_chunks", cfg, query=question)["results"]

# main.py — document listing goes through the gate
info = call_tool("list_documents", cfg)
```

The same door that would govern a future LLM agent already governs the current UI.

---

## Layered trust (why it's robust)

| Layer | Guarantees |
|-------|-----------|
| The gate (`allowed_tools`) | Only these 2 functions exist; only declared args allowed; everything audited. |
| The capability (`document_tools`) | Validates its own input, caps its own workload, read-only, takes no path. |
| Helpers (`file_policy`, `retriever`) | `list_upload_files` re-confines to `data/`; `retrieve` only does vector math. |

Each layer assumes the one above might fail and re-checks anyway. There is no single
line you can break to escape the cage.

---

## One-sentence takeaway

> The allow-list is a plain Python dict with two entries; `call_tool` refuses anything
> not in it — by name *and* by argument — logging every decision; and the two allowed
> functions are themselves so narrow (no paths, self-validating, workload-capped) that
> even *what's allowed is harmless*.

**Tests:** `tests/test_allowed_tools.py` asserts the registry has exactly these two
tools, unknown tools are denied, unexpected parameters are rejected, and both tools
dispatch correctly.
