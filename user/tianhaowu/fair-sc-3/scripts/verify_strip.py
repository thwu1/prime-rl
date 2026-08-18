#!/usr/bin/env python
"""Verify the preserve_all_thinking=false bridge-gate fix: reconstruct each multi-turn
rollout's last-turn CONTEXT from the trajectory `nodes` token_ids and count prior-turn
</think> tokens. STRIP working -> ~0 retained; STILL PRESERVING -> ~num_turns-1.

Usage: uv run --no-sync --with transformers python verify_strip.py <run_dir>
  <run_dir> e.g. /checkpoint/ram/tianhaowu/qwen35_35b_12k_100k_lr1e6_nopreserve/20260702-170428
"""
import json, glob, sys
from transformers import AutoTokenizer

tok = AutoTokenizer.from_pretrained("/checkpoint/ram/tianhaowu/Qwen3.5-35B-A3B", trust_remote_code=True)
TE = tok.convert_tokens_to_ids("</think>")

rundir = sys.argv[1].rstrip("/")
files = glob.glob(f"{rundir}/run_default/rollouts/step_*/train_rollouts.jsonl")
if not files:
    print("no train_rollouts dumps yet"); sys.exit(0)
files.sort(key=lambda p: int(p.split("step_")[1].split("/")[0]))
f = files[-1]; step = f.split("step_")[1].split("/")[0]
rows = [json.loads(l) for l in open(f)]

def depth(nodes, i):
    d = 0; p = nodes[i].get("parent")
    while p is not None: d += 1; p = nodes[p].get("parent")
    return d

res = []
for r in sorted(rows, key=lambda x: (x.get("metrics") or {}).get("num_turns", 0), reverse=True)[:6]:
    nt = (r.get("metrics") or {}).get("num_turns", 0)
    if nt < 8: continue
    nodes = r["nodes"]
    s = [i for i, n in enumerate(nodes) if n.get("sampled") and n.get("token_ids")]
    if not s: continue
    last = max(s, key=lambda i: depth(nodes, i))
    chain = []; p = nodes[last].get("parent")
    while p is not None: chain.append(p); p = nodes[p].get("parent")
    ids = [t for i in chain[::-1] for t in nodes[i].get("token_ids", [])]
    res.append((int(nt), ids.count(TE), len(ids)))

print(f"step {step}: {len(rows)} rollouts; multi-turn sampled:")
for nt, ret, n in res:
    print(f"  turns={nt:>3} ctx={n:>6}tok  prior</think>_retained={ret:>3}  (~0=STRIP, ~{nt-1}=PRESERVE)")
if not res:
    print("VERDICT: no multi-turn rollouts yet (need >=8 turns to test the bridge)")
elif all(ret <= 1 for _, ret, _ in res):
    print("VERDICT: ✅ STRIP WORKING (fix effective)")
elif all(ret >= nt * 0.5 for nt, ret, _ in res):
    print("VERDICT: ❌ STILL PRESERVING (fix not applied / not picked up)")
else:
    print("VERDICT: ⚠️ MIXED — inspect")
