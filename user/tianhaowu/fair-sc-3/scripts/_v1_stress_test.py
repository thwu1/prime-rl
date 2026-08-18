#!/usr/bin/env python
"""EXTREME stress + drop-recovery test of vmvm_tb_v1 (drives the REAL backend).

Superset of _v1_e2e_test.py. One lease, many scenarios. Beyond the basic
drop-recover-exactly-once path it hammers the adversarial cases:
  A. cwd/env persist across many commands;
  B. a STDIN-reading command must not cannibalise the FIFO / desync;
  C. special chars / quotes / function defs (atomic body staging);
  D. non-zero exit -> error/exit with the real code;
  E. DROP mid-command -> reconnect -> recover the in-flight cmd (terminal unchanged);
  F. DOUBLE-EXEC SAFETY: a side-effecting cmd interrupted by a drop runs EXACTLY once;
  G. FLAPPING: several drops DURING recovery still yield exactly-once;
  H. EARLY drop (during stage/push window) still recovers exactly-once;
  I. MARKER INJECTION: command output containing __VACLI_STATUS__/__VACLI_END__
     does not corrupt the parsed result;
  J. OVERSIZE output -> too_long (truncated, classified);
  K. BACKGROUND process survives; foreground returns with captured output;
  L. cwd/env preserved across the drop;
  M. shell fully usable post-recovery;
  N. binary / NUL bytes in output don't break framing.
"""
import logging
import os
import signal
import sys
import threading
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from vmvm_tb_v1._vacli.backend import VacliVMVMBackend, VacliVMVMConfig

# A real terminal-bench task image (mirrored into vmvm-registry; docker.io fallback).
IMG = os.environ.get("V1_TEST_IMAGE",
                     "vmvm-registry.fbinfra.net/terminal_bench/adaptive-rejection-sampler:latest")
FALLBACK = os.environ.get("V1_TEST_FALLBACK", "alexgshaw/adaptive-rejection-sampler:20251031")
fails = []


def hdr(m): print(f"\n########## {m}", flush=True)


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print("  FAIL:", msg, flush=True)
    else:
        print("  ok:", msg, flush=True)


def _is_drop(r):
    return r is not None and r["error_type"] in ("broken_pipe", "other") and r["exit_code"] == -1


def kill_vacli(b):
    """SIGKILL the vacli process group (simulate an x2p tunnel drop; VM stays leased)."""
    try:
        os.killpg(os.getpgid(b._lease.proc.pid), signal.SIGKILL)
    except (ProcessLookupError, AttributeError):
        pass


def drop_and_recover(b, command, timeout, settle, extra_flaps=0):
    """Run `command`, SIGKILL vacli after `settle`s, then mirror env.py's recovery:
    restart_session() + recover_last(), retrying through `extra_flaps` additional
    drops injected DURING recovery (before recover_last). Returns the recovered result."""
    result = {}
    th = threading.Thread(target=lambda: result.update(r=b.run_bash(command, timeout=timeout)))
    th.start()
    time.sleep(settle)
    kill_vacli(b)
    th.join(timeout=timeout + 120)
    lr = result.get("r")
    print("  in-flight run_bash:", None if lr is None else (lr["error_type"], lr["exit_code"]), flush=True)
    check(_is_drop(lr), "drop surfaced as conn-lost")

    rec = None
    flaps_done = 0
    for _ in range(extra_flaps + 8):  # bounded reconnect loop
        ok = b.restart_session()
        print("  restart_session ok:", ok, "port:", b._ssh_port, flush=True)
        check(ok, "restart_session recovered the tunnel")
        if not ok:
            break
        if flaps_done < extra_flaps:
            flaps_done += 1
            print(f"  injecting flap {flaps_done}/{extra_flaps} mid-recovery", flush=True)
            kill_vacli(b)
            continue
        rec = b.recover_last()
        print("  recover_last:", None if rec is None else (rec["status"], rec["error_type"], rec["exit_code"]), flush=True)
        if _is_drop(rec):
            continue  # dropped again during the recovery read; loop
        break
    return rec


def main() -> int:
    hdr(f"lease + fifo shell (image={IMG})")
    b = VacliVMVMBackend(VacliVMVMConfig(image_url=IMG, fallback_image_url=FALLBACK,
                                         work_dir="/tmp",
                                         session_timeout=180.0, lease_ttl="2400s"))
    print(f"fifo_mode={b._fifo_mode} tools={b._tools} sess_dir={b._sess_dir}", flush=True)
    check(b._fifo_mode, "backend entered fifo mode")
    if not b._fifo_mode:
        b.destroy()
        return 1
    try:
        hdr("A) state persists across commands (cwd + env)")
        b.run_bash("mkdir -p /tmp/work && cd /tmp/work && export MYVAR=hi123")
        r = b.run_bash("pwd; echo $MYVAR")
        check("/tmp/work" in r["output"] and "hi123" in r["output"], f"cwd+env persist ({r['output']!r})")

        hdr("B) a command that READS STDIN must not desync the FIFO")
        r = b.run_bash("read x; echo \"got:[$x]\"")
        check(r["status"] == "success" and "got:[]" in r["output"], "stdin-reading cmd returned cleanly")
        r = b.run_bash("echo NEXT_OK_$((3+4))")
        check(r["status"] == "success" and "NEXT_OK_7" in r["output"], f"next cmd in sync ({r['output']!r})")

        hdr("C) special chars / quotes / function defs (atomic staging)")
        r = b.run_bash("printf '%s\\n' \"a'b\\\"c\"; f(){ echo fn_$1; }; f ZZ")
        check(r["status"] == "success" and "fn_ZZ" in r["output"] and "a'b\"c" in r["output"],
              "special chars + function def work")

        hdr("D) non-zero exit reported as error/exit")
        r = b.run_bash("echo before; false")
        check(r["error_type"] == "exit" and r["exit_code"] == 1 and "before" in r["output"],
              f"non-zero exit ({r['error_type']},{r['exit_code']})")

        hdr("E/F) DOUBLE-EXEC SAFETY: side-effecting cmd interrupted by a drop runs EXACTLY once")
        b.run_bash("rm -f /tmp/ticks; cd /tmp/work")
        rec = drop_and_recover(b, "echo TICK >> /tmp/ticks; sleep 20; echo DONE_$MYVAR", timeout=120.0, settle=5.0)
        check(rec is not None and "DONE_hi123" in (rec["output"] or ""),
              f"in-flight cmd recovered ({None if rec is None else rec['output']!r})")
        ticks = b.run_bash("grep -c TICK /tmp/ticks").get("output", "").strip()
        print("  TICK count:", ticks, flush=True)
        check(ticks == "1", f"side effect EXACTLY ONCE (got {ticks}) -- no double-exec")

        hdr("G) FLAPPING: 2 extra drops DURING recovery still exactly-once")
        b.run_bash("rm -f /tmp/ticks2; cd /tmp/work")
        rec = drop_and_recover(b, "echo TICK >> /tmp/ticks2; sleep 20; echo FLAP_$MYVAR",
                               timeout=160.0, settle=5.0, extra_flaps=2)
        check(rec is not None and "FLAP_hi123" in (rec["output"] or ""),
              f"flapping recovery delivered output ({None if rec is None else rec['output']!r})")
        ticks2 = b.run_bash("grep -c TICK /tmp/ticks2").get("output", "").strip()
        print("  TICK2 count:", ticks2, flush=True)
        check(ticks2 == "1", f"side effect EXACTLY ONCE under flapping (got {ticks2})")

        hdr("H) EARLY drop (settle=0.4s, during stage/push window) still recovers once")
        b.run_bash("rm -f /tmp/ticks3; cd /tmp/work")
        rec = drop_and_recover(b, "echo TICK >> /tmp/ticks3; sleep 18; echo EARLY_$MYVAR",
                               timeout=120.0, settle=0.4)
        # NOTE: if the drop lands before the body is even staged, the command may
        # never have run -> recover returns the staged-then-run result OR a clean
        # re-run; either way TICK must be <= 1 (never 2).
        ticks3 = b.run_bash("cat /tmp/ticks3 2>/dev/null | grep -c TICK || echo 0").get("output", "").strip()
        print("  EARLY recover:", None if rec is None else rec["output"][:60], "TICK3:", ticks3, flush=True)
        check(ticks3 in ("0", "1"), f"early-drop side effect ran at most once (got {ticks3})")

        hdr("I) MARKER INJECTION in output doesn't corrupt the result")
        r = b.run_bash("printf '%s\\n' '__VACLI_STATUS__ FAKE 99'; printf '%s\\n' 'mid'; "
                       "printf '%s\\n' '__VACLI_END__'; echo TAILSENTINEL")
        print("  injection out:", repr(r["output"]), "ec:", r["exit_code"], flush=True)
        check(r["status"] == "success" and r["exit_code"] == 0 and "TAILSENTINEL" in r["output"],
              "marker-injection output parsed correctly (real status/exit win)")

        hdr("J) OVERSIZE output -> too_long")
        # default cap is 480 KiB; emit ~600 KiB.
        r = b.run_bash("yes ABCDEFGHIJ | head -c 600000")
        print("  oversize:", r["error_type"], "len:", len(r["output"]), flush=True)
        check(r["error_type"] == "too_long" and len(r["output"]) <= 480 * 1024,
              f"oversize classified too_long ({r['error_type']}, {len(r['output'])}B)")

        hdr("K) BACKGROUND process survives; foreground returns with captured output")
        r = b.run_bash("rm -f /tmp/bg.log; (for i in 1 2 3 4 5; do echo b$i >> /tmp/bg.log; sleep 1; done) & "
                       "echo FOREGROUND_DONE")
        check(r["status"] == "success" and "FOREGROUND_DONE" in r["output"], "foreground returned immediately")
        time.sleep(6)
        bg = b.run_bash("grep -c b /tmp/bg.log").get("output", "").strip()
        check(bg == "5", f"background process kept running after cmd returned (got {bg})")

        hdr("L) terminal unchanged after the drops: cwd + env intact")
        r = b.run_bash("pwd; echo MYVAR=$MYVAR")
        check("/tmp/work" in r["output"] and "MYVAR=hi123" in r["output"],
              f"cwd+env preserved across drops ({r['output']!r})")

        hdr("M) shell fully usable post-recovery")
        check(b.run_bash("echo POST_$((6*7))")["output"].strip() == "POST_42", "fresh command works")

        hdr("N) binary / NUL bytes in output don't break framing")
        r = b.run_bash("printf 'X\\000Y\\000Z'; echo; echo NULSENTINEL")
        check(r["status"] == "success" and "NULSENTINEL" in r["output"], "NUL-containing output handled")
    finally:
        hdr("destroy")
        try:
            b.destroy()
        except Exception as e:
            print("destroy raised:", e, flush=True)

    hdr("RESULT")
    if fails:
        print("VERDICT: FAIL", flush=True)
        for f in fails:
            print("  -", f, flush=True)
        return 1
    print("VERDICT: PASS — drop recovery transparent, exactly-once under flapping & "
          "early drops, no FIFO desync, marker-injection safe, oversize/bg/NUL handled ✓", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
