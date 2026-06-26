#!/usr/bin/env python
"""Benchmark v0 vs v1 backends: per-command LATENCY and drop RELIABILITY.

LATENCY: runs each of several command shapes N times and reports the per-call
wall-time distribution. v1's FIFO protocol does ~4 ssh round-trips per command
(stage + push + wait + cleanup) vs v0's ~1 streamed call, so v1 is expected to be
slower per command — this quantifies the cost of drop-recovery.

RELIABILITY: induces a tunnel drop (SIGKILL vacli) mid-command, then recovers
exactly as env.py does (restart_session + recover_last for v1; restart_session +
re-run for v0). Reports, per backend: recovery rate, exactly-once rate (the
side-effect ran exactly 1x), and recovery latency. v0 has no resume path, so a
drop loses the whole box (recovery rate ~0); v1 resumes the same VM.
"""
import os
import signal
import statistics
import sys
import threading
import time

from vmvm_tb._vacli.backend import VacliVMVMBackend as B0, VacliVMVMConfig as C0
from vmvm_tb_v1._vacli.backend import VacliVMVMBackend as B1, VacliVMVMConfig as C1

IMG = os.environ.get("V1_TEST_IMAGE", "vmvm-registry.fbinfra.net/code_exec/code_exec:full")
N = int(os.environ.get("BENCH_N", "30"))
TRIALS = int(os.environ.get("BENCH_TRIALS", "6"))

LAT_CMDS = [
    ("noop (protocol overhead)", "true"),
    ("echo (tiny output)", "echo hi"),
    ("seq 1..5000 (~24KB)", "seq 1 5000"),
    ("200KB output", "yes ABCDEFGHIJKLMNOPQRST | head -c 200000"),
]


def make(which):
    cfg_cls, b_cls = (C0, B0) if which == "v0" else (C1, B1)
    return b_cls(cfg_cls(image_url=IMG, work_dir="/tmp", session_timeout=180.0, lease_ttl="2400s"))


def kill_vacli(b):
    try:
        os.killpg(os.getpgid(b._lease.proc.pid), signal.SIGKILL)
        return True
    except (ProcessLookupError, AttributeError):
        return False


def conn_lost(r):
    return isinstance(r, dict) and r.get("error_type") in ("broken_pipe", "other") and r.get("exit_code") == -1


def stats(ts):
    ts = sorted(ts)
    pct = lambda p: ts[min(len(ts) - 1, int(round(p / 100 * (len(ts) - 1))))]
    return dict(n=len(ts), mean=statistics.mean(ts), median=statistics.median(ts),
                p90=pct(90), p99=pct(99), mn=ts[0], mx=ts[-1])


def bench_latency(name, b):
    print(f"\n=== LATENCY {name} (N={N} each) ===", flush=True)
    rows = {}
    for label, cmd in LAT_CMDS:
        b.run_bash(cmd, 30)  # warmup
        ts = []
        for _ in range(N):
            t0 = time.perf_counter()
            r = b.run_bash(cmd, 30)
            ts.append(time.perf_counter() - t0)
        s = stats(ts)
        rows[label] = s
        print(f"  {label:32} mean={s['mean']*1000:7.1f}ms  median={s['median']*1000:7.1f}ms  "
              f"p90={s['p90']*1000:7.1f}ms  p99={s['p99']*1000:7.1f}ms  max={s['mx']*1000:7.1f}ms", flush=True)
    return rows


def drop_trial(b, name, i, settle):
    """Induce a mid-command drop, recover like env.py. Returns (recovered, tick_count, latency, box_dead)."""
    tick = f"/tmp/rel_{name}_{i}"
    b.run_bash(f"rm -f {tick}", 20)
    cmd = f"echo TICK >> {tick}; sleep 12; echo DONE_{i}"
    inflight = {}
    th = threading.Thread(target=lambda: inflight.update(r=b.run_bash(cmd, 60)))
    th.start()
    time.sleep(settle)
    kill_vacli(b)
    th.join(timeout=120)

    t0 = time.perf_counter()
    recovered, rec = False, None
    for _ in range(6):
        ok = b.restart_session() if hasattr(b, "restart_session") else False
        if not ok:
            break
        if hasattr(b, "recover_last"):
            rec = b.recover_last()
            if rec is None:
                break  # legacy/shell-reset
            if conn_lost(rec):
                continue  # flapped
            recovered = f"DONE_{i}" in (rec.get("output") or "")
            break
        else:
            rec = b.run_bash(cmd, 60)  # v0: re-run on fresh shell (state lost)
            recovered = not conn_lost(rec) and f"DONE_{i}" in (rec.get("output") or "")
            break
    latency = time.perf_counter() - t0

    box_dead = not recovered and (rec is None or conn_lost(rec))
    tick_count = None
    cr = b.run_bash(f"grep -c TICK {tick} 2>/dev/null || echo X", 20)
    if not conn_lost(cr):
        tick_count = (cr.get("output") or "").strip()
    return recovered, tick_count, latency, box_dead


def bench_reliability(name, trials, settle=4.0):
    print(f"\n=== RELIABILITY {name} ({trials} induced drops, settle={settle}s) ===", flush=True)
    b = make(name)
    rec_n, once_n, latencies, leases = 0, 0, [], 1
    for i in range(trials):
        recovered, ticks, lat, dead = drop_trial(b, name, i, settle)
        if recovered:
            rec_n += 1
            latencies.append(lat)
        if ticks == "1":
            once_n += 1
        print(f"  trial {i}: recovered={recovered} ticks={ticks} rec_latency={lat:.1f}s "
              f"{'[box dead -> re-lease]' if dead else ''}", flush=True)
        if dead and i < trials - 1:
            try:
                b.destroy()
            except Exception:
                pass
            b = make(name)
            leases += 1
    try:
        b.destroy()
    except Exception:
        pass
    print(f"  >> {name}: recovered {rec_n}/{trials}, exactly-once {once_n}/{trials}, "
          f"mean recovery latency {statistics.mean(latencies):.1f}s" if latencies else
          f"  >> {name}: recovered {rec_n}/{trials}, exactly-once {once_n}/{trials}, (no successful recoveries)",
          flush=True)
    print(f"     (used {leases} lease(s); a re-lease means the drop killed the box)", flush=True)


def main():
    print(f"image={IMG} N={N} TRIALS={TRIALS}", flush=True)
    print("leasing v0...", flush=True)
    b0 = make("v0")
    print(f"  v0 port {b0._ssh_port}", flush=True)
    print("leasing v1...", flush=True)
    b1 = make("v1")
    print(f"  v1 port {b1._ssh_port} fifo={b1._fifo_mode}", flush=True)

    bench_latency("v0", b0)
    bench_latency("v1", b1)
    try:
        b0.destroy()
    except Exception:
        pass
    try:
        b1.destroy()
    except Exception:
        pass

    bench_reliability("v0", TRIALS)
    bench_reliability("v1", TRIALS)
    print("\nDONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
