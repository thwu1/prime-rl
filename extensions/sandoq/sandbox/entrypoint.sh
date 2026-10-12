#!/usr/bin/env bash
# Launch BOTH servers in one container:
#   - ttyd  on :7681  -> human browser terminal   (portUrls.terminal)
#   - exec  on :8000  -> structured JSON exec API  (portUrls.exec)
# NOTE: these are two INDEPENDENT bash sessions. They share the pod's filesystem
# and network, but NOT cwd / env / shell state.
set -uo pipefail

# ttyd in the background (best-effort; the exec API governs container liveness).
ttyd -p 7681 -i 0.0.0.0 -W bash &

# exec API in the foreground: if it dies, the container dies (and gets recycled).
exec uvicorn exec_server:app --host 0.0.0.0 --port 8000 --workers 1
