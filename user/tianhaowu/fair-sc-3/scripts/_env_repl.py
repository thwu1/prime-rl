#!/usr/bin/env python
"""Interactive REPL for the vmvm_tb env backends — drive a leased VM by hand,
exactly like the agent does (send a command, see stdout/stderr + exit code), and
optionally compare v0 and v1 SIDE BY SIDE on the same image.

WHY: lets you eyeball edge cases (long-running commands, huge output, and a
tunnel DROP mid-command) and see how v0 vs v1 behave differently — v1 recovers
the in-flight command transparently; v0 cannot reconnect after a tunnel drop.

RUN IT (needs a cpu node with the x2p sidecar -> use the _env_repl.sh wrapper,
or do it by hand inside an interactive allocation):

    srun --partition=cpu --qos=cpu_lowest --account=ram --time=02:00:00 \
         --nodes=1 --ntasks=1 --pty bash
    cd /storage/home/tianhaowu/prime-rl
    PYTHONPATH=environments/vmvm_tb:environments/vmvm_tb_v1 \
        uv run --no-sync python user/tianhaowu/fair-sc-3/scripts/_env_repl.py --env both

REPL commands:
    <anything else>        run it as a bash command on the leased VM('s)
    :drop                  simulate a tunnel drop, then reconnect (no in-flight cmd)
    :dropcmd [Ns] <cmd>    run <cmd>, drop the tunnel after N s (default 3), then
                           reconnect + recover — THE headline v1 feature
    :timeout <sec>         set the per-command timeout (default 120)
    :raw                   toggle full vs truncated output display
    :info                  show container id / ssh port / fifo_mode per backend
    :help                  show this
    :q | :quit | Ctrl-D    destroy the lease(s) and exit
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# v0 = environments/vmvm_tb (pristine), v1 = environments/vmvm_tb_v1 (FIFO drop-recovery).
# Both packages are import-distinct; backend.py is stdlib-only (no verifiers/vllm),
# so `uv run --no-sync` is enough.
BACKENDS_IMPORT = {
    "v0": ("vmvm_tb._vacli.backend", "vmvm_tb (pristine, no drop-recovery)"),
    "v1": ("vmvm_tb_v1._vacli.backend", "vmvm_tb_v1 (FIFO shell, drop-recovery)"),
}

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
GREEN, RED, YELLOW, CYAN = "\033[32m", "\033[31m", "\033[33m", "\033[36m"


def _import_backend(which):
    mod_name, _desc = BACKENDS_IMPORT[which]
    import importlib
    mod = importlib.import_module(mod_name)
    return mod.VacliVMVMBackend, mod.VacliVMVMConfig


def kill_vacli(b):
    """SIGKILL the vacli process group (simulate an x2p tunnel drop; VM stays leased)."""
    try:
        os.killpg(os.getpgid(b._lease.proc.pid), signal.SIGKILL)
        return True
    except (ProcessLookupError, AttributeError):
        return False


def _fmt_result(name, r, elapsed, raw):
    out = r.get("output", "") if isinstance(r, dict) else str(r)
    status = r.get("status") if isinstance(r, dict) else "?"
    ec = r.get("exit_code") if isinstance(r, dict) else "?"
    et = r.get("error_type") if isinstance(r, dict) else "?"
    color = GREEN if status == "success" else (YELLOW if et in ("timeout", "too_long") else RED)
    head = (f"{BOLD}{CYAN}── {name} ──{RESET} {color}status={status} exit={ec} "
            f"error_type={et}{RESET} {DIM}{elapsed:.2f}s out={len(out)}B{RESET}")
    body = out
    if not raw and len(out) > 6000:
        body = out[:3000] + f"\n{DIM}...[{len(out) - 4500} bytes omitted]...{RESET}\n" + out[-1500:]
    return head + "\n" + body


def _norm(r):
    if not isinstance(r, dict):
        return (None, None)
    return (r.get("exit_code"), (r.get("output") or "").rstrip())


def _safe_run(b, command, timeout):
    try:
        return b.run_bash(command, timeout)
    except Exception as e:
        return {"status": "error", "output": f"raised: {type(e).__name__}: {e}",
                "error_type": "other", "exit_code": -1}


def conn_lost(r):
    return isinstance(r, dict) and r.get("error_type") in ("broken_pipe", "other") and r.get("exit_code") == -1


def _reconnect_and_finish(name, b, command, timeout):
    """Mirror env.py: on a detected drop, reconnect to the SAME box and finish the
    command. v1 recovers the in-flight command via recover_last (exactly-once); v0
    has no recover_last, so the shell is reset and the command is re-run."""
    notes = [f"{YELLOW}[{name}] drop detected -> reconnecting{RESET}"]
    if not hasattr(b, "restart_session"):
        notes.append(f"{RED}[{name}] no restart_session -> box lost{RESET}")
        return {"status": "error", "output": "\n".join(notes), "error_type": "other", "exit_code": -1}
    for _ in range(6):
        ok = b.restart_session()
        notes.append(f"{DIM}[{name}] restart_session={ok} port={getattr(b, '_ssh_port', '?')}{RESET}")
        if not ok:
            notes.append(f"{RED}[{name}] box unrecoverable{RESET}")
            return {"status": "error", "output": "\n".join(notes), "error_type": "other", "exit_code": -1}
        if hasattr(b, "recover_last"):
            rec = b.recover_last()
            if rec is None:
                notes.append(f"{YELLOW}[{name}] shell was reset (state lost); re-issue your command{RESET}")
                return {"status": "error", "output": "\n".join(notes), "error_type": "broken_pipe", "exit_code": -1}
            if conn_lost(rec):
                notes.append(f"{DIM}[{name}] flapped during recovery; retrying{RESET}")
                continue
            notes.append(f"{GREEN}[{name}] RECOVERED in-flight command (exactly-once):{RESET}")
            rec = dict(rec)
            rec["output"] = "\n".join(notes) + "\n" + (rec.get("output") or "")
            return rec
        else:
            notes.append(f"{YELLOW}[{name}] no recover_last; re-running on fresh shell (state lost){RESET}")
            rec = _safe_run(b, command, timeout)
            if conn_lost(rec):
                continue
            rec = dict(rec)
            rec["output"] = "\n".join(notes) + "\n" + (rec.get("output") or "")
            return rec
    notes.append(f"{RED}[{name}] still dropping after retries{RESET}")
    return {"status": "error", "output": "\n".join(notes), "error_type": "broken_pipe", "exit_code": -1}


def run_one(name, b, command, timeout, results, recover=True):
    t0 = time.perf_counter()
    r = _safe_run(b, command, timeout)
    if recover and conn_lost(r):
        r = _reconnect_and_finish(name, b, command, timeout)
    results[name] = (r, time.perf_counter() - t0)


def run_with_drop(name, b, command, timeout, settle, results):
    """Run command, SIGKILL vacli after `settle`s (simulate an x2p drop mid-command),
    then reconnect + finish exactly as env.py does."""
    t0 = time.perf_counter()
    inflight = {}
    th = threading.Thread(target=lambda: inflight.update(r=_safe_run(b, command, timeout)))
    th.start()
    time.sleep(settle)
    killed = kill_vacli(b)
    th.join(timeout=timeout + 120)
    lr = inflight.get("r")
    print(f"{DIM}[{name}] dropped vacli ({'killed' if killed else 'no proc'}); "
          f"in-flight returned: {None if lr is None else (lr.get('error_type'), lr.get('exit_code'))}{RESET}")
    r = _reconnect_and_finish(name, b, command, timeout)
    results[name] = (r, time.perf_counter() - t0)


def parallel_run(fn, backends, *args):
    results = {}
    threads = [threading.Thread(target=fn, args=(name, b, *args, results)) for name, b in backends.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def render(results, backends, raw):
    for name in backends:
        r, elapsed = results.get(name, ({}, 0.0))
        print(_fmt_result(name, r, elapsed, raw))
    if len(backends) > 1:
        norms = {n: _norm(results.get(n, ({}, 0))[0]) for n in backends}
        uniq = set(norms.values())
        if len(uniq) == 1:
            print(f"{GREEN}{BOLD}[MATCH]{RESET} v0 and v1 produced identical exit_code + output")
        else:
            print(f"{YELLOW}{BOLD}[DIFF]{RESET} outputs/exit differ: " +
                  ", ".join(f"{n}=exit{norms[n][0]}/{len(norms[n][1] or '')}B" for n in backends))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", choices=["v0", "v1", "both"], default="both")
    ap.add_argument("--image", default=os.environ.get(
        "V1_TEST_IMAGE", "vmvm-registry.fbinfra.net/code_exec/code_exec:full"))
    ap.add_argument("--workdir", default="/tmp")
    ap.add_argument("--timeout", type=float, default=120.0, help="default per-command timeout (s)")
    ap.add_argument("--session-timeout", type=float, default=300.0)
    ap.add_argument("--lease-ttl", default="2400s")
    args = ap.parse_args()

    if not os.environ.get("X2P_PROXY_URL"):
        print(f"{YELLOW}WARNING: X2P_PROXY_URL is unset — vacli leasing needs the x2p sidecar. "
              f"Run this inside a cpu-node srun allocation.{RESET}")

    which = ["v0", "v1"] if args.env == "both" else [args.env]
    print(f"{BOLD}Leasing {', '.join(which)} on image {args.image} ...{RESET}")

    backends = {}
    errs = {}

    # Lease SEQUENTIALLY, not concurrently: vacli assigns the local tunnel port and
    # two simultaneous leases both grab the default port 10000 -> the tunnels collide
    # and every command dies. Leasing one at a time lets the second vacli see 10000
    # taken and pick a free port.
    for name in which:
        try:
            Backend, Config = _import_backend(name)
            cfg = Config(image_url=args.image, work_dir=args.workdir,
                         session_timeout=args.session_timeout, lease_ttl=args.lease_ttl)
            print(f"  leasing {name} ...", flush=True)
            backends[name] = Backend(cfg)
        except Exception as e:
            errs[name] = e

    for name in which:
        if name in errs:
            print(f"{RED}FAILED to lease {name}: {type(errs[name]).__name__}: {errs[name]}{RESET}")
        elif name in backends:
            b = backends[name]
            print(f"{GREEN}leased {name}{RESET}: container={getattr(b, '_container_id', '?')} "
                  f"port={getattr(b, '_ssh_port', '?')} fifo_mode={getattr(b, '_fifo_mode', 'n/a')}")
    if not backends:
        return 1
    backends = {n: backends[n] for n in which if n in backends}  # preserve order
    ports = [getattr(b, "_ssh_port", None) for b in backends.values()]
    if len(set(ports)) != len(ports):
        print(f"{RED}WARNING: backends share an ssh port {ports} — tunnels will collide. "
              f"Re-run; leasing is sequential so this should be rare.{RESET}")

    timeout = args.timeout
    raw = False
    print(f"\n{BOLD}Ready.{RESET} timeout={timeout}s. Type a command, or :help. cwd starts at {args.workdir}.")
    backends_init_cd = parallel_run(run_one, backends, f"cd {args.workdir}", 30.0)

    while True:
        try:
            line = input(f"{BOLD}{CYAN}vmvm[{','.join(backends)}]${RESET} ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        line = line.strip()
        if not line:
            continue
        if line in (":q", ":quit", ":exit"):
            break
        if line == ":help":
            print(__doc__)
            continue
        if line == ":raw":
            raw = not raw
            print(f"raw output display: {raw}")
            continue
        if line == ":info":
            for name, b in backends.items():
                info = b.get_debugging_info() if hasattr(b, "get_debugging_info") else {}
                print(f"  {name}: fifo_mode={getattr(b, '_fifo_mode', 'n/a')} "
                      f"sess_dir={getattr(b, '_sess_dir', 'n/a')} {info}")
            continue
        if line.startswith(":timeout"):
            try:
                timeout = float(line.split()[1])
                print(f"per-command timeout = {timeout}s")
            except (IndexError, ValueError):
                print("usage: :timeout <seconds>")
            continue
        if line == ":drop":
            print(f"{DIM}simulating tunnel drop + reconnect (no in-flight cmd)...{RESET}")
            res = parallel_run(run_with_drop, backends, ":", 30.0, 0.2)
            render(res, backends, raw)
            continue
        if line.startswith(":dropcmd"):
            rest = line[len(":dropcmd"):].strip()
            settle = 3.0
            parts = rest.split(maxsplit=1)
            if parts and parts[0].endswith("s") and parts[0][:-1].replace(".", "", 1).isdigit():
                settle = float(parts[0][:-1])
                rest = parts[1] if len(parts) > 1 else ""
            if not rest:
                print("usage: :dropcmd [Ns] <command>   e.g. :dropcmd 5s sleep 30; echo done")
                continue
            print(f"{DIM}running + dropping vacli after {settle}s, then reconnect+recover...{RESET}")
            res = parallel_run(run_with_drop, backends, rest, timeout, settle)
            render(res, backends, raw)
            continue

        res = parallel_run(run_one, backends, line, timeout)
        render(res, backends, raw)

    print(f"{BOLD}destroying lease(s)...{RESET}")
    for name, b in backends.items():
        try:
            b.destroy()
        except Exception as e:
            print(f"  {name} destroy raised: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
