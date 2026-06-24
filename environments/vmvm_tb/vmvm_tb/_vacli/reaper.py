"""Orphan-vacli reaper (env-side safety net).

A hard-killed env worker leaves its `vacli lease` children running, reparented
to init (PPID==1), auto-renewing their VM lease forever -> leaked VM. This
daemon finds those orphans and SIGTERMs them so vacli's --release-on-exit frees
the VM; SIGKILLs stragglers (stops auto-renew -> lease expires at TTL). It also
counts zombie (defunct) vacli for observability, and logs both every tick.
Node-singleton via an flock so co-resident processes do not both run it.
"""
import fcntl
import logging
import os
import signal
import threading
import time

logger = logging.getLogger(__name__)

_INTERVAL_S = 30.0
_MIN_AGE_S = 120.0       # PPID==1 is already definitive; this is just a race guard
_BATCH = 200            # max SIGTERMs per cycle (don't flood the VMVM control plane)
_SIGKILL_AFTER_S = 90.0
_LOCK_PATH = "/tmp/vmvm_vacli_reaper.lock"
_started = False
_lock_fh = None


def _read(p):
    try:
        with open(p, "rb") as f:
            return f.read()
    except OSError:
        return b""


def _is_vacli_lease(pid):
    parts = _read("/proc/%d/cmdline" % pid).split(b"\x00")
    return any(b"vacli" in c for c in parts) and b"lease" in parts


def scan():
    """One pass over /proc -> (orphan_pids, defunct_count)."""
    try:
        tck = os.sysconf("SC_CLK_TCK")
    except Exception:
        tck = 100
    try:
        uptime = float(_read("/proc/uptime").split()[0])
    except Exception:
        uptime = 0.0
    orphans, defunct = [], 0
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        pid = int(d)
        stat = _read("/proc/%d/stat" % pid)
        rp = stat.rfind(b")")
        if rp < 0:
            continue
        comm = stat[stat.find(b"(") + 1:rp]
        if b"vacli" not in comm:        # matches zombies too (they have no cmdline)
            continue
        f = stat[rp + 2:].split()
        if not f:
            continue
        if f[0] == b"Z":                # zombie / defunct
            defunct += 1
            continue
        try:
            ppid = int(f[1])
            starttime = int(f[19])
        except (IndexError, ValueError):
            continue
        if ppid == 1 and (uptime - starttime / tck) >= _MIN_AGE_S and _is_vacli_lease(pid):
            orphans.append(pid)
    return orphans, defunct


def _killpg(pid, sig):
    try:
        os.killpg(os.getpgid(pid), sig)
    except (ProcessLookupError, PermissionError):
        pass


def _loop():
    sent = {}
    while True:
        try:
            now = time.monotonic()
            orphans, defunct = scan()
            oset = set(orphans)
            killed = 0
            for pid, t0 in list(sent.items()):
                if pid not in oset:
                    del sent[pid]                          # released + gone
                elif now - t0 > _SIGKILL_AFTER_S:
                    _killpg(pid, signal.SIGKILL)           # straggler -> TTL expiry
                    killed += 1
            fresh = [p for p in orphans if p not in sent][:_BATCH]
            for pid in fresh:
                _killpg(pid, signal.SIGTERM)               # --release-on-exit
                sent[pid] = now
            logger.info(
                "vacli-reaper tick: orphans=%d defunct=%d sigtermed=%d sigkilled=%d tracked=%d",
                len(orphans), defunct, len(fresh), killed, len(sent),
            )
        except Exception as e:
            logger.error("vacli-reaper cycle error: %s", e)
        time.sleep(_INTERVAL_S)


def start_reaper_once():
    """Start the reaper daemon thread; only one wins the node-level flock."""
    global _started, _lock_fh
    if _started:
        return
    _started = True
    try:
        _lock_fh = open(_LOCK_PATH, "w")
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        logger.info("vacli-reaper: node lock held elsewhere; not starting here")
        return
    threading.Thread(target=_loop, name="vacli-orphan-reaper", daemon=True).start()
    logger.info("vacli-reaper: started (interval=%.0fs, batch=%d)", _INTERVAL_S, _BATCH)
