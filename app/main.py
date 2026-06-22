"""Streamlit UI for the sandboxed AI assistant.

Runs startup/preflight, then renders upload + indexing + Q&A. Document access goes
exclusively through the explicit tool boundary (`app.tools.allowed_tools.call_tool`)
— the UI never touches the filesystem or a shell directly. Every meaningful action
emits a structured audit event via `app.logger.audit`.
"""

from __future__ import annotations

# Ensure the project root (parent of this file's `app/` package) is importable,
# regardless of how the app is launched. Streamlit runs this file as a script, so
# sys.path[0] is the `app/` dir, not the project root — without this, `import app`
# fails. PYTHONPATH=/app in the container covers the same case; this is a belt-and-
# suspenders fallback for local `streamlit run app/main.py`.
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st

from app.logger import audit
from app.rag.embeddings import EmbeddingError
from app.rag.loaders import LoaderError, load_document
from app.rag.qa import answer_question
from app.rag.vector_store import VectorStoreError, index_document
from app.security.file_policy import FilePolicyError, store_upload
from app.startup import ConfigError, run_startup
from app.tools.allowed_tools import ToolExecutionError, available_tools, call_tool


def _boot():
    """Run preflight once per session and cache the config."""
    if "cfg" not in st.session_state:
        st.session_state.cfg = run_startup()
    return st.session_state.cfg


def main() -> None:
    st.set_page_config(page_title="Sandboxed AI Assistant", page_icon="🔒", layout="wide")

    try:
        cfg = _boot()
    except ConfigError as exc:
        st.error(f"Configuration error: {exc}")
        st.stop()
        return

    st.title("🔒 Sandboxed AI Assistant")
    st.caption(
        "A secure-by-default document Q&A assistant. Fully local — no external API, "
        "no credentials, no data leaves this container."
    )

    with st.sidebar:
        st.header("Security posture")
        st.markdown(
            "- ✅ Runs in a hardened container (non-root, read-only rootfs)\n"
            "- ✅ Writes only to the dedicated data directory\n"
            "- ✅ Minimal explicit tool allow-list\n"
            "- ✅ No external network calls / no secrets required\n"
            "- ✅ Structured audit logging"
        )
        st.divider()
        st.caption("Allowed capabilities (least privilege)")
        for tool in available_tools():
            st.markdown(f"- `{tool['name']}` — {tool['description']}")
        st.caption("Any tool not in this list is denied by default.")

        st.divider()
        st.caption("Configuration")
        st.json(
            {
                "data_dir": str(cfg.data_dir),
                "allowed_extensions": sorted(cfg.allowed_extensions),
                "max_upload_mb": cfg.max_upload_mb,
                "embedding_model": cfg.embedding_model,
                "retrieval_top_k": cfg.retrieval_top_k,
            }
        )

    col_left, col_right = st.columns([3, 2])
    with col_left:
        _render_ask(cfg)
    with col_right:
        _render_upload(cfg)
        _render_document_list(cfg)


def _render_ask(cfg) -> None:
    st.subheader("💬 Ask your documents")

    try:
        info = call_tool("list_documents", cfg)
    except VectorStoreError:
        info = {"indexed_chunks": 0}

    if info.get("indexed_chunks", 0) == 0:
        st.caption("Upload a document first, then ask a question about it.")
        return

    question = st.text_input(
        "Your question",
        placeholder="e.g. What does the document say about access control?",
        key="question",
    )
    ask = st.button("Ask", type="primary")

    if not (ask and question.strip()):
        return

    try:
        with st.spinner("Retrieving relevant passages…"):
            ans = answer_question(question, cfg)
    except (VectorStoreError, EmbeddingError, ToolExecutionError) as exc:
        audit("qa_failed", reason=str(exc))
        st.error(f"Could not answer: {exc}")
        return

    audit(
        "question_asked",
        # The question text is part of the audit trail; no secrets involved.
        question=question.strip(),
        grounded=ans.grounded,
        sources=[
            {"stored_name": src.get("stored_name"), "score": src.get("score")}
            for src in ans.sources
        ],
    )

    st.markdown("### Answer")
    (st.success if ans.grounded else st.warning)(ans.text)

    st.markdown("### 🔎 Sources")
    if not ans.sources:
        st.caption("No source chunks retrieved.")
        return
    for i, src in enumerate(ans.sources, start=1):
        label = (
            f"{i}. {src.get('stored_name', 'unknown')} "
            f"· chunk {src.get('chunk_index')} · relevance {src.get('score'):.2f}"
        )
        with st.expander(label):
            st.write(src.get("text", ""))


def _render_upload(cfg) -> None:
    st.subheader("📤 Upload documents")
    allowed = ", ".join(sorted(cfg.allowed_extensions))
    st.caption(f"Allowed types: {allowed} · Max size: {cfg.max_upload_mb} MB per file")

    uploaded = st.file_uploader(
        "Choose one or more documents",
        type=[e.lstrip(".") for e in sorted(cfg.allowed_extensions)],
        accept_multiple_files=True,
        key="uploader",
    )
    if not uploaded:
        return

    # Track which uploads we've already stored this session to avoid Streamlit
    # rerun duplication.
    handled: set[str] = st.session_state.setdefault("handled_uploads", set())

    newly_indexed = False
    for file in uploaded:
        content = file.getvalue()
        dedupe_key = f"{file.name}:{len(content)}"
        if dedupe_key in handled:
            continue
        try:
            meta = store_upload(file.name, content, cfg)
        except FilePolicyError as exc:
            audit("upload_rejected", filename=file.name, reason=str(exc))
            st.error(f"❌ {file.name}: {exc}")
            continue
        handled.add(dedupe_key)
        audit(
            "upload_stored",
            original_name=meta["original_name"],
            stored_name=meta["stored_name"],
            size_bytes=meta["size_bytes"],
            sha256=meta["sha256"],
            extension=meta["extension"],
        )
        st.success(
            f"✅ Stored **{meta['stored_name']}** "
            f"({meta['size_bytes']:,} bytes · sha256 {meta['sha256'][:12]}…)"
        )
        if _index_stored(meta, cfg):
            newly_indexed = True

    # The Ask panel (left column) renders BEFORE this upload handler, so a
    # just-indexed document wouldn't unlock it until the next interaction. Rerun
    # once so the whole page re-evaluates with the new index state.
    if newly_indexed:
        st.rerun()


def _index_stored(meta: dict, cfg) -> bool:
    """Load + chunk + embed + persist a freshly stored document.

    Returns True if new chunks were actually indexed (i.e. the page should rerun
    so the Ask panel picks up the new index state).
    """
    try:
        with st.spinner(f"Indexing {meta['stored_name']}…"):
            text = load_document(meta["path"], cfg)
            result = index_document(
                doc_hash=meta["sha256"],
                stored_name=meta["stored_name"],
                text=text,
                cfg=cfg,
            )
    except (LoaderError, VectorStoreError, EmbeddingError) as exc:
        audit("index_failed", stored_name=meta["stored_name"], reason=str(exc))
        st.warning(f"⚠️ Stored but not indexed — {exc}")
        return False
    audit(
        "index_completed",
        stored_name=meta["stored_name"],
        doc_hash=meta["sha256"],
        chunks=result["chunks"],
        skipped=result["skipped"],
    )
    if result["skipped"]:
        st.caption(f"↪︎ {meta['stored_name']} was already indexed.")
        return False
    st.caption(f"🔎 Indexed {result['chunks']} chunk(s) from {meta['stored_name']}.")
    return True


def _render_document_list(cfg) -> None:
    try:
        info = call_tool("list_documents", cfg)
    except VectorStoreError:
        info = {"documents": [], "indexed_documents": 0, "indexed_chunks": 0}

    docs = info.get("documents", [])
    st.subheader(f"📚 Stored documents ({len(docs)})")
    st.caption(
        f"Index: {info.get('indexed_documents', 0)} document(s) · "
        f"{info.get('indexed_chunks', 0)} chunk(s)."
    )
    if not docs:
        st.caption("No documents uploaded yet.")
        return
    st.table(
        [
            {"Document": d["name"], "Size (KB)": round(d["size_bytes"] / 1024, 1)}
            for d in docs
        ]
    )


if __name__ == "__main__":
    main()
