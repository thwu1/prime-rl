#!/bin/bash
# Interactive REPL launcher for the vmvm_tb env backends (v0 / v1 / both).
# Grabs a cpu node (whose prolog runs the x2pagentd sidecar vacli needs) with a
# pty and drops you into the REPL. Pass through args, e.g.:
#   bash user/tianhaowu/fair-sc-3/scripts/_env_repl.sh --env both
#   bash user/tianhaowu/fair-sc-3/scripts/_env_repl.sh --env v1 --image <img> --timeout 600
#
# WHY THE EXPLICIT X2P EXPORTS: `srun --pty` does NOT propagate the prolog/SPANK
# injected x2p env into the task (and your login shell doesn't have it either).
# x2pagentd still runs on the node, so the SSH tunnel comes up — but without
# X2P_PROXY_URL the x2p data path is unstable and every command dies with
# connection-lost right after setup. The address is a fixed infra constant
# (10.0.2.2:10054 on every cpu node), so we set it here; any inherited value wins.
set -u
REPO=/storage/home/tianhaowu/prime-rl
X2P_URL="${X2P_PROXY_URL:-http://10.0.2.2:10054/}"
X2P_E="${X2P_ENV:-cloud}"
X2P_CFG="${X2P_CFG_ENV:-CLOUD}"

srun --partition=cpu --qos=cpu_lowest --account=ram --time=02:00:00 \
     --nodes=1 --ntasks=1 --export=ALL --pty \
     bash -lc "export X2P_PROXY_URL='${X2P_URL}' X2P_ENV='${X2P_E}' X2P_CFG_ENV='${X2P_CFG}'; \
       cd $REPO && PYTHONPATH=environments/vmvm_tb:environments/vmvm_tb_v1 \
       uv run --no-sync python -u user/tianhaowu/fair-sc-3/scripts/_env_repl.py $*"
