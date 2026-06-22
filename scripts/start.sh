#!/usr/bin/env bash
# One-command setup + launch for the Sandboxed AI Assistant (macOS / Linux).
#
#   ./scripts/start.sh
#
# Checks .env, creates required directories, then launches the hardened
# container with docker compose.

set -euo pipefail

# Resolve repo root (this script lives in scripts/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "🔒 Sandboxed AI Assistant — startup"
echo "-----------------------------------"

# 1. Docker present?
if ! command -v docker >/dev/null 2>&1; then
  echo "❌ Docker is not installed or not on PATH."
  echo "   Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
  exit 1
fi

# 1b. Docker daemon actually running?
if ! docker info >/dev/null 2>&1; then
  echo "❌ Docker is installed but the daemon isn't responding."
  echo "   Start Docker Desktop (or the docker service) and try again."
  exit 1
fi

# Pick compose command (plugin vs legacy).
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "❌ Docker Compose not found. Update Docker Desktop or install the compose plugin."
  exit 1
fi

# 2. .env present? If not, create it from the template (no secrets needed in V1).
if [ ! -f .env ]; then
  echo "ℹ️  No .env found — creating one from .env.example (V1 needs no API key)."
  cp .env.example .env
  echo "✅ Created .env"
else
  echo "✅ .env found"
fi

# 3. Ensure required writable directories exist on the host (bind-mount targets).
mkdir -p data/uploads data/chroma data/model_cache logs
echo "✅ Data and log directories ready"

# 4. Launch.
echo ""
echo "🚀 Building and starting the container (first build downloads the model once)..."
echo "   When it's up, open:  http://localhost:8501"
echo ""
exec $COMPOSE up --build
