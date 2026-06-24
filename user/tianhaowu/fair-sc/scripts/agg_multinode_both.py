import json, glob, os
keep = {json.loads(l)["Path"].rstrip("/").split("/")[-1]
        for l in open("/checkpoint/ram/tianhaowu/datasets/terminal_bench/v2_harbor_pass80.jsonl")}
tn = lambda r: ((r.get("info") or {}).get("task_name")) or ""
for label, BASE in [("h200x4", "/checkpoint/ram/tianhaowu/vmvm_tb_multinode"),
                    ("h100x8", "/checkpoint/ram/tianhaowu/vmvm_tb_multinode_h100")]:
    rj = sorted(glob.glob(os.path.join(BASE, "**", "results.jsonl"), recursive=True), key=os.path.getmtime)
    if not rj:
        print(f"{label}: no results yet"); continue
    rows = [json.loads(l) for l in open(rj[-1]) if l.strip()]
    by = {}
    for r in rows:
        t = tn(r)
        if t in keep:
            by.setdefault(t, []).append((r.get("reward") or 0) >= 1.0)
    nr = sum(len(v) for v in by.values()); np_ = sum(sum(v) for v in by.values())
    solved = sum(1 for v in by.values() if any(v))
    print(f"{label}: rollouts={nr} tasks={len(by)}/80  pass@1={np_}/{nr}={round(100*np_/max(nr,1),1)}%  pass@k(any)={solved}/{len(by)}={round(100*solved/max(len(by),1),1)}%")
