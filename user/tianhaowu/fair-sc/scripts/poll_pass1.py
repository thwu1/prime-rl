import json, glob, os
keep={json.loads(l)["Path"].rstrip("/").split("/")[-1] for l in open("/checkpoint/ram/tianhaowu/datasets/terminal_bench/v2_harbor_pass80.jsonl")}
cands=sorted(glob.glob(os.path.expanduser("~/prime-rl/environments/vmvm_tb/outputs/evals/*/*/results.jsonl")), key=os.path.getmtime)
if not cands:
    print("NO_RESULTS_YET"); raise SystemExit
R=cands[-1]
rows=[json.loads(l) for l in open(R) if l.strip()]
tn=lambda r:((r.get("info") or {}).get("task_name")) or ""
inset=[r for r in rows if tn(r) in keep]
n=len(inset); p=sum(1 for r in inset if (r.get("reward") or 0)>=1.0)
print(f"file={R}")
print(f"total_rows={len(rows)}  pass80: completed={n}/80  passed={p}  pass@1={round(100*p/max(n,1))}%")
