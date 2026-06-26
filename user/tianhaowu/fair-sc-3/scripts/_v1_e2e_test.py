#!/usr/bin/env python
"""E2E + hardening test of vmvm_tb_v1 Stage-2 drop recovery (drives the REAL backend).

Covers the primary drop-recovery path AND the edge cases the adversarial review
flagged:
  A. shell state persists across many commands (cwd/env, file cleanup safe);
  B. a command that READS STDIN does not cannibalise the FIFO / desync the protocol;
  C. special chars / quotes / function defs in a command body (atomic staging);
  D. non-zero exit is reported as error/exit with the real code;
  E. DROP mid-command -> reconnect -> recover the in-flight command (terminal unchanged);
  F. DOUBLE-EXEC SAFETY: a side-effecting command interrupted by a drop runs EXACTLY ONCE.
"""
import logging
import os
import signal
import sys
import threading
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from vmvm_tb_v1._vacli.backend import VacliVMVMBackend, VacliVMVMConfig

IMG = os.environ.get("V1_TEST_IMAGE", "vmvm-registry.fbinfra.net/code_exec/code_exec:full")
fails = []


def hdr(m): print(f"\n########## {m}", flush=True)
def check(cond, msg):
    if not cond: fails.append(msg); print("  FAIL:", msg, flush=True)
    else: print("  ok:", msg, flush=True)


def drop_during(b, command, timeout, settle=5.0):
    """Run `command` in a thread, SIGKILL vacli after `settle`s, return the result
    after restart_session + recover_last. Mirrors what env.py does on a drop."""
    result = {}
    th = threading.Thread(target=lambda: result.update(r=b.run_bash(command, timeout=timeout)))
    th.start()
    time.sleep(settle)
    try:
        os.killpg(os.getpgid(b._lease.proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    th.join(timeout=timeout + 60)
    lr = result.get("r")
    print("  in-flight run_bash:", None if lr is None else (lr["error_type"], lr["exit_code"]), flush=True)
    check(lr is not None and lr["error_type"] in ("broken_pipe", "other") and lr["exit_code"] == -1,
          "drop surfaced as conn-lost")
    ok = b.restart_session()
    print("  restart_session ok:", ok, "new_port:", b._ssh_port, flush=True)
    check(ok, "restart_session recovered the tunnel")
    rec = b.recover_last()
    print("  recover_last:", None if rec is None else (rec["status"], rec["error_type"], rec["exit_code"],
          repr(rec["output"])[:120]), flush=True)
    return rec


def main() -> int:
    hdr(f"lease + fifo shell (image={IMG})")
    b = VacliVMVMBackend(VacliVMVMConfig(image_url=IMG, work_dir="/tmp",
                                         session_timeout=180.0, lease_ttl="1800s"))
    print(f"fifo_mode={b._fifo_mode} tools={b._tools} sess_dir={b._sess_dir}", flush=True)
    check(b._fifo_mode, "backend entered fifo mode")
    if not b._fifo_mode:
        b.destroy(); return 1
    try:
        hdr("A) state persists across commands (cwd + env)")
        b.run_bash("mkdir -p /tmp/work && cd /tmp/work && export MYVAR=hi123")
        r = b.run_bash("pwd; echo $MYVAR")
        check("/tmp/work" in r["output"] and "hi123" in r["output"], f"cwd+env persist ({r['output']!r})")

        hdr("B) a command that READS STDIN must not desync the FIFO")
        r = b.run_bash("read x; echo \"got:[$x]\"")     # stdin is /dev/null -> EOF -> empty
        print("  stdin-cmd:", r["status"], repr(r["output"]), flush=True)
        check(r["status"] == "success" and "got:[]" in r["output"], "stdin-reading cmd returned cleanly")
        r = b.run_bash("echo NEXT_OK_$((3+4))")          # protocol still in sync?
        check(r["status"] == "success" and "NEXT_OK_7" in r["output"], f"next cmd in sync ({r['output']!r})")

        hdr("C) special chars / quotes / function defs (atomic staging)")
        r = b.run_bash("printf '%s\\n' \"a'b\\\"c\"; f(){ echo fn_$1; }; f ZZ")
        print("  special:", repr(r["output"]), flush=True)
        check(r["status"] == "success" and "fn_ZZ" in r["output"] and "a'b\"c" in r["output"],
              "special chars + function def work")

        hdr("D) non-zero exit reported as error/exit")
        r = b.run_bash("echo before; false")
        check(r["error_type"] == "exit" and r["exit_code"] == 1 and "before" in r["output"],
              f"non-zero exit ({r['error_type']},{r['exit_code']})")
        check(b.run_bash("echo STILL_OK")["output"].strip() == "STILL_OK", "shell alive after non-zero exit")

        hdr("F) DOUBLE-EXEC SAFETY: side-effecting cmd interrupted by a drop runs EXACTLY once")
        b.run_bash("rm -f /tmp/ticks; cd /tmp/work")
        rec = drop_during(b, "echo TICK >> /tmp/ticks; sleep 22; echo DONE_$MYVAR", timeout=120.0, settle=5.0)
        check(rec is not None and "DONE_hi123" in (rec["output"] or ""),
              f"in-flight side-effecting cmd recovered ({None if rec is None else rec['output']!r})")
        ticks = b.run_bash("grep -c TICK /tmp/ticks").get("output", "").strip()
        print("  TICK count:", ticks, flush=True)
        check(ticks == "1", f"side effect happened EXACTLY ONCE (got {ticks} TICKs) -- no double-exec")

        hdr("E) terminal unchanged after recovery: cwd + env intact")
        r = b.run_bash("pwd; echo MYVAR=$MYVAR")
        check("/tmp/work" in r["output"] and "MYVAR=hi123" in r["output"],
              f"cwd+env preserved across the drop ({r['output']!r})")

        hdr("G) shell fully usable post-recovery")
        check(b.run_bash("echo POST_$((6*7))")["output"].strip() == "POST_42", "fresh command works")
    finally:
        hdr("destroy")
        try: b.destroy()
        except Exception as e: print("destroy raised:", e, flush=True)

    hdr("RESULT")
    if fails:
        print("VERDICT: FAIL", flush=True)
        for f in fails: print("  -", f, flush=True)
        return 1
    print("VERDICT: PASS — drop recovery transparent, no double-exec, no FIFO desync, "
          "state preserved, edge cases handled ✓", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
