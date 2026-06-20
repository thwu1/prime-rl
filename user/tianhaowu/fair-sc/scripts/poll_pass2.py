import json, glob, os
keep={json.loads(l)["Path"].rstrip("/").split("/")[-1] for l in open("/checkpoint/ram/tianhaowu/datasets/terminal_bench/v2_harbor_pass80.jsonl")}
cands=sorted(glob.glob(os.path.expanduser("~/prime-rl/environments/vmvm_tb/outputs/evals/*/*/results.jsonl")), key=os.path.getmtime)
if not cands:
    print("NO_RESULTS_YET"); raise SystemExit
R=cands[-1]
rows=[json.loads(l) for l in open(R) if l.strip()]
tn=lambda r:((r.get("info") or {}).get("task_name")) or ""
by={}
for r in rows:
    t=tn(r)
    if t in keep:
        by.setdefault(t,[]).append((r.get("reward") or 0)>=1.0)
solved=sum(1 for t,v in by.items() if any(v)); tasks=len(by); rollouts=sum(len(v) for v in by.values())
print(f"file={R}")
print(f"rollouts={rollouts} tasks_seen={tasks}/80  pass@2(any): solved={solved}/{tasks}  rate={round(100*solved/max(tasks,1))}%")
