#!/usr/bin/env python3
# Design-C external monitor (v2: time-windowed live set).
# Parses a run's orchestrator.log into per-rollout + per-EXAMPLE dashboards.
# "live" = rollouts whose last ROLLOUT_STATE beacon is within WINDOW seconds of
# the newest beacon, so completed/stale rollouts drop out (fixes the inflated
# done/live counts). Rows are keyed by gid; note gid is stamped on the shared
# example dict, so a row aggregates concurrent groups of the SAME example
# (labelled per-example). Aggregates (pass rate, turns, pulls) are exact.
# Usage: rollout_monitor.py [outdir_or_log ...] [--groups N] [--window S]
import sys, re, glob, os
from collections import Counter, defaultdict
import statistics
from datetime import datetime

WINDOW = 400  # seconds: a beacon older than this (vs newest) = not live

ANSI = re.compile(r"\x1b\[[0-9;]*m")
TS = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
RS_NEW = re.compile(r"ROLLOUT_STATE rid=(\d+) gid=(\S+) task=(\S+) state=(\S+) turn=(\d+) "
                    r"t_setup=([\d.]+) t_run=([\d.]+) timeout=(\S+) sub=(\S*)")
RS_OLD = re.compile(r"ROLLOUT_STATE rid=(\d+) task=(\S+) state=(\S+) turn=(\d+) "
                    r"t_setup=([\d.]+) t_run=([\d.]+) timeout=(\S+) sub=(\S*)")
DONE_NEW = re.compile(r"ROLLOUT DONE (?:rid=(\S+) )?gid=(\S+) task=(\S+) reward=(\S+) outcome=(\S+) turns=(\d+)")
DONE_OLD = re.compile(r"ROLLOUT DONE task=(\S+) reward=(\S+) outcome=(\S+) turns=(\d+)")
PULL = re.compile(r"podman pull (?:failed for )?\S*[/:]([a-z0-9._-]+?)(?::latest)?\b"
                  r".*?attempt (\d+)/(\d+).*?rate_limited=(\w+)")

def latest(stem):
    ds = sorted(glob.glob(f"/checkpoint/ram/tianhaowu/{stem}/*/"))
    return ds[-1] if ds else None

def resolve(arg):
    if os.path.isdir(arg):
        c = glob.glob(os.path.join(arg, "logs/orchestrator.log")) or \
            glob.glob(os.path.join(arg, "**/orchestrator.log"), recursive=True)
        return c[0] if c else os.path.join(arg, "logs/orchestrator.log")
    return arg

def parse_ts(line):
    m = TS.search(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        return None

def run_one(arg, topn, window):
    log = resolve(arg)
    if not os.path.exists(log):
        print(f"[no log: {log}]"); return
    lines = open(log, errors="replace").read().splitlines()[-400000:]
    live, pulling, threads = {}, {}, None
    done = []
    done_by_gid = Counter()
    newest = 0.0
    for ln in lines:
        m = RS_NEW.search(ln)
        gid = None
        if m:
            rid, gid, task, st, turn, ts_s, tr, to, sub = m.groups()
        else:
            m = RS_OLD.search(ln)
            if m:
                rid, task, st, turn, ts_s, tr, to, sub = m.groups()
        if m:
            t = parse_ts(ln) or 0.0
            newest = max(newest, t)
            live[rid] = dict(gid=gid, task=task, state=st, turn=int(turn),
                             t_setup=float(ts_s), t_run=float(tr), sub=sub, ts=t)
            continue
        c = ANSI.sub("", ln)
        d = DONE_NEW.search(c)
        if d:
            _rid_d, g, task, rew, out, turns = d.groups()
            done.append((task, rew, out, int(turns))); done_by_gid[g] += 1
            continue
        d = DONE_OLD.search(c)
        if d:
            done.append((d.group(1), d.group(2), d.group(3), int(d.group(4)))); continue
        p = PULL.search(ln)
        if p:
            pulling[p.group(1)] = (int(p.group(2)), int(p.group(3)), p.group(4))
        t = re.search(r"threads_total=(\d+)", ln)
        if t: threads = int(t.group(1))

    # Exclude completed rollouts (state=done beacon) from the live set.
    # Before the done-beacon patch, these appeared as "stuck in grading" because
    # ROLLOUT DONE only logged gid, making per-rid completion invisible.
    done_rids = {r for r, v in live.items() if v["state"] == "done"}
    all_rids = dict(live)  # keep a copy for wedged analysis
    live = {r: v for r, v in live.items() if r not in done_rids}

    # Window the live set to genuinely-active rollouts
    wedged = {}
    if newest and any(v["ts"] for v in live.values()):
        wedged = {r: v for r, v in live.items() if v["ts"] < newest - window}
        live = {r: v for r, v in live.items() if v["ts"] >= newest - window}

    print("="*94)
    print(f"ROLLOUT MONITOR  {os.path.basename(os.path.dirname(os.path.dirname(log)))}/{os.path.basename(os.path.dirname(log))}"
          f"   (live = beacon within {window}s; rows are per-example)")
    print("="*94)

    have_gid = any(v["gid"] for v in live.values())
    if have_gid and live:
        groups = defaultdict(lambda: {"live": [], "task": None})
        for v in live.values():
            if v["gid"]:
                groups[v["gid"]]["live"].append(v); groups[v["gid"]]["task"] = v["task"]
        rows = []
        for gid, g in groups.items():
            lv = g["live"]; sc = Counter(x["state"] for x in lv)
            # t_setup = total elapsed since rollout start (setup+run) for ALL states,
            # so "oldest" is TOTAL runtime of the longest-lived rollout, not run-phase only
            oldest = max(x["t_setup"] for x in lv) if lv else 0.0
            turns = sorted((x["turn"] for x in lv if x["state"] == "running"), reverse=True)
            rows.append(dict(gid=gid[:8], task=(g["task"] or "?")[:26], active=len(lv),
                             setup=sc.get("setup",0), run=sc.get("running",0), grade=sc.get("grading",0),
                             oldest=oldest, turns=turns))
        rows.sort(key=lambda r: r["active"], reverse=True)
        active_total = sum(r["active"] for r in rows)
        print(f"ACTIVE rollouts: {active_total} across {len(rows)} examples in flight "
              f"(showing top {min(topn,len(rows))} by activity)\n")
        print(f"{'gid':<9}{'example':<27}{'actv':>5}{'setup':>6}{'run':>4}{'grade':>6}{'oldest':>8}  run turns")
        for r in rows[:topn]:
            print(f"{r['gid']:<9}{r['task']:<27}{r['active']:>5}{r['setup']:>6}{r['run']:>4}{r['grade']:>6}"
                  f"{r['oldest']:>7.0f}s  {','.join(str(x) for x in r['turns'][:8])}")
    elif live:
        print("(no gid= on beacons — pre-patch run)")
    else:
        print("(no live beacons in window)")

    if live:
        sc = Counter(v["state"] + ("/"+v["sub"] if v["sub"] else "") for v in live.values())
        print("\nLIVE per-state:", dict(sc))
    if wedged:
        wsc = Counter(v["state"] for v in wedged.values())
        oldest_w = max((newest - v["ts"]) for v in wedged.values()) if wedged else 0
        state_str = ", ".join(f"{s}={c}" for s, c in sorted(wsc.items(), key=lambda x: -x[1]))
        print(f"WEDGED (outside window, no done beacon): {len(wedged)}  oldest={oldest_w:.0f}s  [{state_str}]")
    if pulling:
        nrl = sum(1 for _, (_, _, rl) in pulling.items() if rl.lower() == "true")
        print(f"PULLING (recent): {len(pulling)} tasks  rate_limited={nrl}")
    if done:
        turns = [d[3] for d in done]; npass = sum(1 for d in done if d[2] == "pass")
        print(f"COMPLETED(window): {len(done)} | pass {npass} ({100*npass/len(done):.0f}%) | "
              f"turns med={int(statistics.median(turns))} max={max(turns)}")
    print(f"threads_total: {threads}")

raw = sys.argv[1:]
topn, window, args = 12, WINDOW, []
i = 0
while i < len(raw):
    if raw[i] == "--groups": topn = int(raw[i+1]); i += 2; continue
    if raw[i] == "--window": window = int(raw[i+1]); i += 2; continue
    args.append(raw[i]); i += 1
targets = args or [d for d in (latest("tb_rl_12k_200k_lr1e5_dtype32_rr"),
                               latest("tb_rl_17k_200k_lr1e5_dtype32_rr")) if d]
for t in targets:
    run_one(t, topn, window)
