
import json
import os
import sys

from metrics import compute_metrics
from simulator import Simulator
from workload import generate_workload
from scheduler.fcfs import FCFSScheduler


def run_scheduler(scheduler, workload, trace_path=None):
    sim = Simulator(scheduler, workload, trace_path=trace_path)
    completed = sim.run()
    return compute_metrics(completed, sim.memory), completed, sim


def main():
    workload = generate_workload()
    mode = sys.argv[1] if len(sys.argv) > 1 else "fcfs"

    trace_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traces")
    os.makedirs(trace_dir, exist_ok=True)

    if mode == "baseline":
        trace_path = os.path.join(trace_dir, "baseline.jsonl")
        m, _, _ = run_scheduler(FCFSScheduler(), workload, trace_path=trace_path)
        print(json.dumps(m, indent=2))
        print(f"\nTrace written to {trace_path}", file=sys.stderr)

    elif mode == "custom":
        from scheduler.paged_mlfq import PagedMLFQScheduler
        trace_path = os.path.join(trace_dir, "custom.jsonl")
        m, _, _ = run_scheduler(PagedMLFQScheduler(), workload, trace_path=trace_path)
        print(json.dumps(m, indent=2))

    elif mode == "compare":
        fm, fc, fsim = run_scheduler(FCFSScheduler(), workload)

        from scheduler.paged_mlfq import PagedMLFQScheduler
        trace_path = os.path.join(trace_dir, "custom.jsonl")
        cm, cc, csim = run_scheduler(PagedMLFQScheduler(), workload,
                                      trace_path=trace_path)

        short_f = [r for r in fc if r.input_tokens <= 100]
        short_c = [r for r in cc if r.input_tokens <= 100]

        ratios = {
            "avg_jct": cm["avg_jct"] / fm["avg_jct"] if fm["avg_jct"] > 0 else 0,
            "p99_jct": cm["p99_jct"] / fm["p99_jct"] if fm["p99_jct"] > 0 else 0,
        }
        if short_f and short_c:
            sf_avg = sum(r.jct for r in short_f) / len(short_f)
            sc_avg = sum(r.jct for r in short_c) / len(short_c)
            ratios["short_avg_jct"] = sc_avg / sf_avg if sf_avg > 0 else 0

        result = {"fcfs": fm, "custom": cm, "ratios": ratios}
        print(json.dumps(result, indent=2))

    else:
        print("Usage: python3 run.py [baseline|custom|compare]")
        sys.exit(1)


if __name__ == "__main__":
    main()
