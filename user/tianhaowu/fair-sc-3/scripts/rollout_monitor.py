#!/usr/bin/env python3
# Design-C external monitor. Parses a run's orchestrator.log into per-rollout +
# PER-GROUP dashboards. Uses ROLLOUT_STATE beacons (env.py, now with gid=) to
# join each gen to its group, so you can see how many groups are in flight, how
# many members each has finished, and what every live gen is doing.
# Usage: rollout_monitor.py [run_outdir_or_orchestrator.log] [--groups N]
import sys, re, glob, os
from collections import Counter, defaultdict
import statistics

ANSI = re.compile(r"\x1b\[[0-9;]*m")
# new format carries gid=; old format (pre-patch) does not -> gid=None
RS_NEW = re.compile(r"ROLLOUT_STATE rid=(\d+) gid=(\S+) task=(\S+) state=(\S+) turn=(\d+) "
                    r"t_setup=([\d.]+) t_run=([\d.]+) timeout=(\S+) sub=(\S*)")
RS_OLD = re.compile(r"ROLLOUT_STATE rid=(\d+) task=(\S+) state=(\S+) turn=(\d+) "
                    r"t_setup=([\d.]+) t_run=([\d.]+) timeout=(\S+) sub=(\S*)")
DONE_NEW = re.compile(r"ROLLOUT DONE gid=(\S+) task=(\S+) reward=(\S+) outcome=(\S+) turns=(\d+)")
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

def run_one(arg, topn=20):
    log = resolve(arg)
    if not os.path.exists(log):
        print(f"[no log: {log}]"); return
    lines = open(log, errors="replace").read().splitlines()[-300000:]
    live, pulling, threads = {}, {}, None      # live[rid] -> latest beacon
    done = []
    done_by_gid = Counter()
    for ln in lines:
        m = RS_NEW.search(ln)
        if m:
            rid, gid, task, st, turn, ts, tr, to, sub = m.groups()
        else:
            m = RS_OLD.search(ln)
            if m:
                rid, task, st, turn, ts, tr, to, sub = m.groups(); gid = None
        if m:
            live[rid] = dict(gid=gid, task=task, state=st, turn=int(turn),
                             t_setup=float(ts), t_run=float(tr), sub=sub)
            continue
        c = ANSI.sub("", ln)
        d = DONE_NEW.search(c)
        if d:
            gid, task, rew, out, turns = d.groups()
            done.append((task, rew, out, int(turns))); done_by_gid[gid] += 1
            continue
        d = DONE_OLD.search(c)
        if d:
            done.append((d.group(1), d.group(2), d.group(3), int(d.group(4)))); continue
        p = PULL.search(ln)
        if p:
            pulling[p.group(1)] = (int(p.group(2)), int(p.group(3)), p.group(4))
        t = re.search(r"threads_total=(\d+)", ln)
        if t: threads = int(t.group(1))

    print("="*92)
    print(f"ROLLOUT MONITOR  {os.path.basename(os.path.dirname(os.path.dirname(log)))}/{os.path.basename(os.path.dirname(log))}")
    print("="*92)

    # ---- PER-GROUP view (join live beacons by gid) ----
    have_gid = any(v["gid"] for v in live.values())
    if have_gid:
        groups = defaultdict(lambda: {"live": [], "task": None})
        for v in live.values():
            if v["state"] == "grading":
                # treat grading as effectively done for fill purposes but still show
                pass
            if v["gid"]:
                groups[v["gid"]]["live"].append(v)
                groups[v["gid"]]["task"] = v["task"]
        rows = []
        for gid, g in groups.items():
            lv = g["live"]
            doneN = done_by_gid.get(gid, 0)
            sc = Counter(x["state"] for x in lv)
            oldest = max((x["t_run"] if x["state"] == "running" else x["t_setup"]) for x in lv) if lv else 0.0
            turns = sorted((x["turn"] for x in lv if x["state"] == "running"), reverse=True)
            rows.append(dict(gid=gid[:8], task=(g["task"] or "?")[:26], done=doneN, live=len(lv),
                             seen=doneN+len(lv), setup=sc.get("setup",0), run=sc.get("running",0),
                             grade=sc.get("grading",0), oldest=oldest, turns=turns))
        rows.sort(key=lambda r: r["oldest"], reverse=True)
        print(f"GROUPS IN FLIGHT: {len(rows)}  (showing {min(topn,len(rows))} most-stalled; target=16/group)\n")
        print(f"{'gid':<9}{'task':<27}{'done':>4}{'live':>5}{'setup':>6}{'run':>4}{'grade':>6}{'oldest':>8}  live turns")
        for r in rows[:topn]:
            tt = ",".join(str(x) for x in r["turns"][:8])
            print(f"{r['gid']:<9}{r['task']:<27}{r['done']:>4}{r['live']:>5}{r['setup']:>6}{r['run']:>4}{r['grade']:>6}{r['oldest']:>7.0f}s  {tt}")
        # drill-down: the single most-stalled group's members
        if rows:
            g0 = rows[0]["gid"]
            mem = [v for v in live.values() if v["gid"] and v["gid"][:8] == g0]
            print(f"\nMOST-STALLED GROUP {g0} ({rows[0]['task']}) members:")
            for v in sorted(mem, key=lambda x: -(x['t_run'] if x['state']=='running' else x['t_setup'])):
                age = v['t_run'] if v['state']=='running' else v['t_setup']
                print(f"  state={v['state']:<8} turn={v['turn']:<4} sub={v['sub']:<6} age={age:.0f}s")
    else:
        print("(no gid= on beacons — pre-patch run; per-group view unavailable)")

    # ---- per-rollout state counts ----
    if live:
        st_counts = Counter(v["state"] + ("/"+v["sub"] if v["sub"] else "") for v in live.values())
        print("\nLIVE per-state:", dict(st_counts))

    if pulling:
        nrl = sum(1 for _, (_, _, rl) in pulling.items() if rl.lower() == "true")
        print(f"\nPULLING (recent, by attempt#): {len(pulling)} tasks  rate_limited={nrl}")
        for task, (att, mx, rl) in sorted(pulling.items(), key=lambda kv: kv[1][0], reverse=True)[:8]:
            print(f"  {task[:42]:<44} attempt {att}/{mx}  rate_limited={rl}")
    if done:
        turns = [d[3] for d in done]
        npass = sum(1 for d in done if d[2] == "pass")
        print(f"\nCOMPLETED(window): {len(done)} | pass {npass} ({100*npass/len(done):.0f}%) | "
              f"turns med={int(statistics.median(turns))} max={max(turns)}")
    print(f"threads_total(leak-watch): {threads}")

raw = sys.argv[1:]
topn = 20
args = []
_i = 0
while _i < len(raw):
    if raw[_i] == "--groups":
        topn = int(raw[_i+1]); _i += 2; continue
    args.append(raw[_i]); _i += 1
targets = args or [d for d in (latest("tb_rl_12k_200k_lr1e5_dtype32_rr"),
                               latest("tb_rl_17k_200k_lr1e5_dtype32_rr")) if d]
for t in targets:
    run_one(t, topn)
