# Sandboxed AI Assistant — container image
#
# Security choices (see docs/security_model.md §2):
#   * slim base, pinned by minor version
#   * dependencies installed as root at build time, app runs as non-root
#   * a dedicated unprivileged user (appuser) owns the data/log dirs
#   * the runtime is further restricted via docker-compose (read-only rootfs,
#     cap_drop ALL, no-new-privileges, tmpfs) — see docker-compose.yml

FROM python:3.12-slim AS base

# Build-time pip behavior + cache-stable interpreter flags. Keep this block
# minimal so it rarely changes — anything here sits ABOVE the pip layer, so
# editing it would bust the (expensive) dependency-install cache.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first for better layer caching: this layer is only
# rebuilt when requirements.txt changes, not when app code changes below.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Runtime-only env, placed AFTER the pip layer so changing it never invalidates
# the dependency install. PYTHONPATH=/app lets the top-level `app` package
# resolve when Streamlit runs app/main.py as a script (sys.path[0] is /app/app).
ENV PYTHONPATH=/app

# Copy application code.
COPY app/ ./app/

# Create a non-root user and the writable directories it owns. These are the
# ONLY paths the app writes to; everything else is read-only at runtime.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/uploads /app/data/chroma /app/data/model_cache /app/logs \
    && chown -R appuser:appuser /app/data /app/logs

USER appuser

EXPOSE 8501

# Healthcheck hits Streamlit's built-in health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health').status==200 else 1)" || exit 1

CMD ["streamlit", "run", "app/main.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
