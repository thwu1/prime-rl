import json, glob, os
KEEP={json.loads(l)["Path"].rstrip("/").split("/")[-1] for l in open("/checkpoint/ram/tianhaowu/datasets/terminal_bench/v2_harbor_pass80.jsonl")}
BASE="/checkpoint/ram/tianhaowu/vmvm_tb_ref_runs"
tn=lambda r:((r.get("info") or {}).get("task_name")) or ""
seeds=sorted(glob.glob(os.path.join(BASE,"seed*")))
per_seed=[]; union={}
for sd in seeds:
    rj=sorted(glob.glob(os.path.join(sd,"**","results.jsonl"),recursive=True),key=os.path.getmtime)
    if not rj: continue
    rows=[json.loads(l) for l in open(rj[-1]) if l.strip()]
    solved={}
    for r in rows:
        t=tn(r)
        if t in KEEP:
            ok=(r.get("reward") or 0)>=1.0
            solved[t]=solved.get(t,False) or ok
            union[t]=union.get(t,False) or ok
    n=len(solved); p=sum(solved.values())
    per_seed.append((os.path.basename(sd),p,n))
    print(f"{os.path.basename(sd)}: pass@1 = {p}/{n} = {round(100*p/max(n,1),1)}%")
if per_seed:
    rates=[100*p/max(n,1) for _,p,n in per_seed]
    mean=sum(rates)/len(rates)
    var=sum((x-mean)**2 for x in rates)/len(rates)
    print(f"\nMEAN pass@1 over {len(per_seed)} runs = {round(mean,1)}%  (std {round(var**0.5,1)})")
    up=sum(union.values()); un=len(union)
    print(f"pass@{len(per_seed)} (union, any run) = {up}/{un} = {round(100*up/max(un,1),1)}%")
