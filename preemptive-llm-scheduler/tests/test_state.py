
import json
import os
import sys

sys.path.insert(0, "/opt/llm-sim")

from workload import generate_workload
from simulator import Simulator
from metrics import compute_metrics
from scheduler.fcfs import FCFSScheduler

CALIBRATION_PATH = "/opt/llm-sim/calibration.json"

# Lazy-loaded simulation state (run once, shared across tests)
_state = {}


def _ensure_loaded():
    if "workload" in _state:
        return

    wl = generate_workload()
    _state["workload"] = wl

    # FCFS baseline
    fsim = Simulator(FCFSScheduler(), wl)
    fc = fsim.run()
    _state["fcfs_completed"] = fc
    _state["fcfs_metrics"] = compute_metrics(fc, fsim.memory)

    # Custom scheduler
    from scheduler.paged_mlfq import PagedMLFQScheduler
    csim = Simulator(PagedMLFQScheduler(), wl)
    cc = csim.run()
    _state["custom_completed"] = cc
    _state["custom_metrics"] = compute_metrics(cc, csim.memory)


# ---- Calibration ----

class TestCalibration:
    def test_calibration_file_exists(self):
        assert os.path.exists(CALIBRATION_PATH), (
            f"Calibration file not found at {CALIBRATION_PATH}. "
            "Network bandwidth must be calibrated before the simulator can run."
        )

    def test_calibration_format_and_values(self):
        with open(CALIBRATION_PATH) as f:
            data = json.load(f)
        assert "measured_bandwidth_gbps" in data, (
            "calibration.json missing 'measured_bandwidth_gbps'"
        )
        assert "remote_memory_bandwidth_mb_s" in data, (
            "calibration.json missing 'remote_memory_bandwidth_mb_s'"
        )
        mbw = data["measured_bandwidth_gbps"]
        rbw = data["remote_memory_bandwidth_mb_s"]
        assert mbw > 1.0, (
            f"measured_bandwidth_gbps={mbw} — unrealistically low"
        )
        assert 100 < rbw < 10000, (
            f"remote_memory_bandwidth_mb_s={rbw} — out of expected range"
        )


# ---- Scheduler existence & interface ----

class TestSchedulerExists:
    def test_import(self):
        from scheduler.paged_mlfq import PagedMLFQScheduler
        assert PagedMLFQScheduler is not None

    def test_is_subclass(self):
        from scheduler.paged_mlfq import PagedMLFQScheduler
        from scheduler.base import Scheduler
        assert issubclass(PagedMLFQScheduler, Scheduler)


# ---- Correctness ----

class TestCorrectness:
    def test_all_requests_complete(self):
        _ensure_loaded()
        n = _state["custom_metrics"]["num_completed"]
        total = len(_state["workload"])
        assert n == total, f"Only {n}/{total} requests completed"

    def test_completion_times_valid(self):
        _ensure_loaded()
        for r in _state["custom_completed"]:
            assert r.completion_time >= r.arrival_time, (
                f"Req {r.id}: completion {r.completion_time} < arrival {r.arrival_time}"
            )
            assert r.completion_time > 0

    def test_no_duplicate_completions(self):
        _ensure_loaded()
        ids = [r.id for r in _state["custom_completed"]]
        assert len(ids) == len(set(ids)), "Duplicate completions detected"


# ---- Performance targets ----

class TestPerformance:
    def test_avg_jct_improvement(self):
        """Overall average JCT must be at most 50% of FCFS."""
        _ensure_loaded()
        fm = _state["fcfs_metrics"]
        cm = _state["custom_metrics"]
        ratio = cm["avg_jct"] / fm["avg_jct"]
        assert ratio <= 0.50, (
            f"Avg JCT ratio {ratio:.4f} > 0.50  "
            f"(custom={cm['avg_jct']:.1f}ms, FCFS={fm['avg_jct']:.1f}ms)"
        )

    def test_short_request_improvement(self):
        """Short-request (input<=100) avg JCT must be at most 25% of FCFS."""
        _ensure_loaded()
        f_short = [r for r in _state["fcfs_completed"] if r.input_tokens <= 100]
        c_short = [r for r in _state["custom_completed"] if r.input_tokens <= 100]
        assert f_short and c_short

        f_avg = sum(r.jct for r in f_short) / len(f_short)
        c_avg = sum(r.jct for r in c_short) / len(c_short)
        ratio = c_avg / f_avg
        assert ratio <= 0.25, (
            f"Short-request JCT ratio {ratio:.4f} > 0.25  "
            f"(custom={c_avg:.1f}ms, FCFS={f_avg:.1f}ms)"
        )

    def test_slo_compliance(self):
        """Overall SLO compliance must be at least 60%."""
        _ensure_loaded()
        cm = _state["custom_metrics"]
        assert cm["slo_compliance"] >= 0.60, (
            f"SLO compliance {cm['slo_compliance']:.4f} < 0.60"
        )


# ---- Scheduling behaviour ----

class TestSchedulingBehavior:
    def test_preemption_occurs(self):
        _ensure_loaded()
        total = _state["custom_metrics"]["total_preemptions"]
        assert total > 0, "No preemptions — scheduler is not preemptive"

    def test_short_faster_than_long(self):
        _ensure_loaded()
        short = [r for r in _state["custom_completed"] if r.input_tokens <= 100]
        long_ = [r for r in _state["custom_completed"] if r.input_tokens >= 1000]
        if short and long_:
            s_avg = sum(r.jct for r in short) / len(short)
            l_avg = sum(r.jct for r in long_) / len(long_)
            assert s_avg < l_avg, (
                f"Short avg JCT ({s_avg:.1f}) >= Long avg JCT ({l_avg:.1f})"
            )
