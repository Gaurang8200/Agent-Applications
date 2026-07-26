#!/usr/bin/env bash
# Dev launcher for the API. On macOS, WeasyPrint's native libraries (pango,
# cairo) live in the Homebrew lib dir, which the dynamic linker does not search
# by default — so PDF rendering fails unless DYLD_FALLBACK_LIBRARY_PATH points
# at it. This wrapper sets that up, then runs uvicorn with whatever args follow.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

if command -v brew >/dev/null 2>&1; then
  export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"
fi

exec "$here/.venv/bin/uvicorn" app.main:app "$@"
