#!/usr/bin/env python
"""Per-step infra/drop + pass breakdown for a prime-rl run's train_rollouts.jsonl.

For each training step it counts, over the rollouts ACTUALLY IN THAT STEP'S BATCH
(run_default/rollouts/step_N/train_rollouts.jsonl), how many were:
  pass      tb_reward > 0
  box_gone  tunnel drop, unrecoverable -> trajectory contains "connection lost permanently"
  reconnect recovered drop (v0 'shell was reset, re-issue') that did NOT box_gone
  setup     "Environment setup failed"
Detection scans the trajectory text, matching the HTML trajectory viewer
(make_vmvm_tb_viewer.infra_flags). box_gone takes priority over reconnect for a
rollout that did both. Usage: analyze_drops_per_step.py <run_dir> [<run_dir> ...]
"""
import sys
import os
import glob
import re

REWARD = re.compile(r'"tb_reward":\s*([0-9.]+)')


def analyze(run):
    base = os.path.join(run, "run_default", "rollouts")
    steps = sorted(glob.glob(os.path.join(base, "step_*")),
                   key=lambda p: int(p.rsplit("step_", 1)[-1]))
    print(f"\n################ {run}")
    hdr = (f"{'step':>5} {'n':>5} {'pass':>5} {'pass%':>6}  "
           f"{'boxgone':>7} {'bg%':>6}  {'recon':>5} {'rec%':>6}  {'setup':>5}  {'infra%':>6}")
    print(hdr)
    print("-" * len(hdr))
    T = dict(n=0, p=0, bg=0, rc=0, su=0)
    for s in steps:
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
                box = "connection lost permanently" in line
                if box:
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
    print(f"INFRA-affected (box_gone+reconnect+setup) = {infra} ({100*infra/n:.1f}%) of train-batch rollouts")


if __name__ == "__main__":
    for run in sys.argv[1:]:
        analyze(run)
