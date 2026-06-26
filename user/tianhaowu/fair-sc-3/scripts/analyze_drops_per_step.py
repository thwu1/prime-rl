#!/usr/bin/env python
"""Per-step infra/x2p-drop + pass breakdown for a prime-rl run's train_rollouts.jsonl.

For each training step it counts, over the rollouts ACTUALLY IN THAT STEP'S BATCH
(run_default/rollouts/step_N/train_rollouts.jsonl), how many were infra-affected.

Two detection modes:
  default (v0): scan the trajectory TEXT (what the model saw) for
                "connection lost permanently" (box_gone) / "shell was reset"
                (recovered reconnect) / "Environment setup failed".
  --v1:         read the SCALAR infra_* metrics the v1 env emits into each rollout's
                `metrics` (infra_box_gone / infra_state_lost / infra_env_error /
                infra_drops / infra_recovered / infra_lost_turn). v1 recovery is
                invisible in the trajectory text, so the v0 mode finds nothing for it;
                this reads the structured signal instead, including WHICH turn was lost.
                (Full per-turn event lists are in logs/envs/train/<env>.log, "ROLLOUT INFRA".)

Detection (v0) matches make_vmvm_tb_viewer.infra_flags. The env-log "box gone" string
undercounts; the jsonl is authoritative. Usage:
  analyze_drops_per_step.py <run_dir> [<run_dir> ...]          # v0 text mode
  analyze_drops_per_step.py --v1 <run_dir> [<run_dir> ...]     # v1 metrics mode
"""
import sys
import os
import glob
import re

REWARD = re.compile(r'"tb_reward":\s*([0-9.]+)')


def _steps(run):
    base = os.path.join(run, "run_default", "rollouts")
    return sorted(glob.glob(os.path.join(base, "step_*")),
                  key=lambda p: int(p.rsplit("step_", 1)[-1]))


def analyze_v0(run):
    """v0: detect infra from trajectory text (the model-visible messages)."""
    print(f"\n################ [v0/text] {run}")
    hdr = (f"{'step':>5} {'n':>5} {'pass':>5} {'pass%':>6}  "
           f"{'boxgone':>7} {'bg%':>6}  {'recon':>5} {'rec%':>6}  {'setup':>5}  {'infra%':>6}")
    print(hdr)
    print("-" * len(hdr))
    T = dict(n=0, p=0, bg=0, rc=0, su=0)
    for s in _steps(run):
        f = os.path.join(s, "train_rollouts.jsonl")
        if not os.path.exists(f):
            continue
        n = p = bg = rc = su = 0
        with open(f, errors="replace") as fh:
            for line in fh:
                if '"tb_reward"' not in line:
                    continue
                n += 1
                m = REWARD.search(line)
                if m and float(m.group(1)) > 0:
                    p += 1
                if "connection lost permanently" in line:
                    bg += 1
                elif "shell was reset" in line:
                    rc += 1
                if "Environment setup failed" in line:
                    su += 1
        if not n:
            continue
        infra = bg + rc + su
        print(f"{int(s.rsplit('step_',1)[-1]):>5} {n:>5} {p:>5} {100*p/n:>5.1f}%  "
              f"{bg:>7} {100*bg/n:>5.1f}%  {rc:>5} {100*rc/n:>5.1f}%  {su:>5}  {100*infra/n:>5.1f}%",
              flush=True)
        for k, v in zip(("n", "p", "bg", "rc", "su"), (n, p, bg, rc, su)):
            T[k] += v
    n = T["n"] or 1
    print("-" * len(hdr))
    infra = T["bg"] + T["rc"] + T["su"]
    print(f"TOTAL n={T['n']}  pass={T['p']} ({100*T['p']/n:.1f}%)  "
          f"box_gone={T['bg']} ({100*T['bg']/n:.1f}%)  reconnect={T['rc']} ({100*T['rc']/n:.1f}%)  "
          f"setup_fail={T['su']} ({100*T['su']/n:.1f}%)")
    print(f"INFRA-affected = {infra} ({100*infra/n:.1f}%) of train-batch rollouts")


_V1KEYS = ("tb_reward", "infra_drops", "infra_recovered", "infra_box_gone",
           "infra_state_lost", "infra_env_error", "infra_lost_turn")
_V1 = {k: re.compile(r'"%s":\s*(-?[0-9.]+)' % k) for k in _V1KEYS}


def analyze_v1(run):
    """v1: read scalar infra_* metrics from each rollout (seamless recovery isn't in text)."""
    print(f"\n################ [v1/metrics] {run}")
    hdr = (f"{'step':>5} {'n':>5} {'pass%':>6}  {'dropRoll':>8} {'drop%':>6} {'recov':>6}  "
           f"{'boxgone':>7} {'bg%':>6} {'stLost':>6} {'envErr':>6}  {'meanLostTurn':>12}")
    print(hdr)
    print("-" * len(hdr))
    T = dict(n=0, p=0, droll=0, recov=0, bg=0, sl=0, ee=0)
    lost_all = []
    seen_metric = False
    for s in _steps(run):
        f = os.path.join(s, "train_rollouts.jsonl")
        if not os.path.exists(f):
            continue
        n = p = droll = recov = bg = sl = ee = 0
        lost = []
        with open(f, errors="replace") as fh:
            for line in fh:
                if '"tb_reward"' not in line:
                    continue
                n += 1
                vals = {}
                for k in _V1KEYS:
                    m = _V1[k].search(line)
                    vals[k] = float(m.group(1)) if m else 0.0
                if "infra_box_gone" in line:
                    seen_metric = True
                if vals["tb_reward"] > 0:
                    p += 1
                if vals["infra_drops"] > 0:
                    droll += 1
                recov += int(vals["infra_recovered"])
                if vals["infra_box_gone"] > 0:
                    bg += 1
                if vals["infra_state_lost"] > 0:
                    sl += 1
                if vals["infra_env_error"] > 0:
                    ee += 1
                if vals["infra_lost_turn"] >= 0:
                    lost.append(vals["infra_lost_turn"])
        if not n:
            continue
        mlt = (sum(lost) / len(lost)) if lost else -1.0
        print(f"{int(s.rsplit('step_',1)[-1]):>5} {n:>5} {100*p/n:>5.1f}%  "
              f"{droll:>8} {100*droll/n:>5.1f}% {recov:>6}  "
              f"{bg:>7} {100*bg/n:>5.1f}% {sl:>6} {ee:>6}  {mlt:>12.1f}", flush=True)
        T["n"] += n; T["p"] += p; T["droll"] += droll; T["recov"] += recov
        T["bg"] += bg; T["sl"] += sl; T["ee"] += ee
        lost_all += lost
    n = T["n"] or 1
    print("-" * len(hdr))
    if not seen_metric:
        print("WARNING: no infra_* metrics found — is this a v1 run with the infra metric funcs? "
              "(older v1/v0 dumps won't have them; use the default text mode for v0.)")
    mlt = (sum(lost_all) / len(lost_all)) if lost_all else -1.0
    print(f"TOTAL n={T['n']}  pass={100*T['p']/n:.1f}%  "
          f"drop_rollouts={T['droll']} ({100*T['droll']/n:.1f}%)  recovered_drops={T['recov']}  "
          f"box_gone={T['bg']} ({100*T['bg']/n:.1f}%)  state_lost={T['sl']} ({100*T['sl']/n:.1f}%)  "
          f"env_error={T['ee']} ({100*T['ee']/n:.1f}%)  mean_lost_turn={mlt:.1f}")


if __name__ == "__main__":
    args = sys.argv[1:]
    v1 = "--v1" in args
    runs = [a for a in args if a != "--v1"]
    if not runs:
        print("usage: analyze_drops_per_step.py [--v1] <run_dir> [<run_dir> ...]")
        sys.exit(2)
    for run in runs:
        (analyze_v1 if v1 else analyze_v0)(run)
