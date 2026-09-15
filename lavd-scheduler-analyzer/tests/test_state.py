"""Tests for CPU affinity optimization task."""
import json
import os
import re
from collections import defaultdict, deque

import pytest



def _read_sysfs():
    """Parse CPU topology from sysfs directory tree."""
    cpus = {}
    sysfs = "/app/data/sysfs"
    for entry in sorted(os.listdir(sysfs)):
        if not entry.startswith("cpu") or not entry[3:].isdigit():
            continue
        cpu_id = int(entry[3:])
        d = os.path.join(sysfs, entry)
        cap = int(open(os.path.join(d, "cpu_capacity")).read().strip())
        power = int(open(os.path.join(d, "power", "active_power_mw")).read().strip())
        cpus[cpu_id] = {"capacity": cap, "power_mw": power}
    return cpus


def _parse_ftrace():
    """Parse ftrace trace to extract task runtimes and wake dependencies."""
    task_runtimes = defaultdict(list)
    task_cpus = {}
    wake_deps = set()
    exec_starts = {}
    pid_to_name = {}

    with open("/app/data/trace.txt") as f:
        for line in f:
            if line.lstrip().startswith("#") or not line.strip():
                continue

            if "sched_switch:" in line:
                m = re.search(
                    r'(\d+\.\d+):\s+sched_switch:.*?'
                    r'prev_comm=(\S+)\s+prev_pid=(\d+).*?prev_state=(\S+).*?'
                    r'next_comm=(\S+)\s+next_pid=(\d+)',
                    line)
                if not m:
                    continue
                ts = float(m.group(1)) * 1e6
                prev_comm, prev_pid = m.group(2), int(m.group(3))
                next_comm, next_pid = m.group(5), int(m.group(6))
                cpu_m = re.search(r'\[(\d+)\]', line)
                cpu = int(cpu_m.group(1))

                if prev_pid != 0 and not prev_comm.startswith("swapper"):
                    pid_to_name[prev_pid] = prev_comm
                    if prev_pid in exec_starts:
                        start_ts, start_cpu = exec_starts[prev_pid]
                        runtime = ts - start_ts
                        task_runtimes[prev_comm].append(runtime)
                        task_cpus[prev_comm] = start_cpu
                        del exec_starts[prev_pid]

                if next_pid != 0 and not next_comm.startswith("swapper"):
                    pid_to_name[next_pid] = next_comm
                    exec_starts[next_pid] = (ts, cpu)

            elif "sched_wakeup:" in line:
                waker_m = re.match(r'\s*(\S+)-(\d+)\s+\[', line)
                if not waker_m:
                    continue
                waker_name = waker_m.group(1)
                waker_pid = int(waker_m.group(2))

                wakee_m = re.search(r'comm=(\S+)\s+pid=(\d+)', line)
                if not wakee_m:
                    continue
                wakee_name = wakee_m.group(1)

                if waker_name.startswith("swapper") or waker_name == "<idle>" or waker_pid == 0:
                    continue

                pid_to_name[waker_pid] = waker_name
                wake_deps.add((waker_name, wakee_name))

    tasks = {}
    for name, rts in task_runtimes.items():
        tasks[name] = {
            "pid": next((p for p, n in pid_to_name.items() if n == name), 0),
            "avg_runtime": sum(rts) / len(rts) if rts else 0,
            "total_runtime": sum(rts),
            "cpu": task_cpus.get(name, 0),
        }
    return tasks, wake_deps, pid_to_name


def _compute_base_runtimes(tasks, cpus):
    """Compute base (capacity-1024) runtimes from observed runtimes."""
    base = {}
    for name, info in tasks.items():
        cpu = info["cpu"]
        cap = cpus[cpu]["capacity"]
        base[name] = {
            "avg": info["avg_runtime"] * cap / 1024,
            "total": info["total_runtime"] * cap / 1024,
        }
    return base


def _build_dag(wake_deps, task_names):
    adj = defaultdict(list)
    in_deg = {n: 0 for n in task_names}
    for src, dst in wake_deps:
        if src in task_names and dst in task_names:
            adj[src].append(dst)
            in_deg[dst] += 1
    return adj, in_deg


def _topo_sort(task_names, adj, in_deg):
    temp = dict(in_deg)
    order = []
    q = deque(n for n in task_names if temp[n] == 0)
    while q:
        n = q.popleft()
        order.append(n)
        for nb in adj[n]:
            temp[nb] -= 1
            if temp[nb] == 0:
                q.append(nb)
    return order


def _longest_path(task_names, adj, in_deg, node_weights):
    topo = _topo_sort(task_names, adj, in_deg)
    dist = {n: node_weights.get(n, 0) for n in task_names}
    for node in topo:
        for nb in adj[node]:
            nd = dist[node] + node_weights.get(nb, 0)
            if nd > dist[nb]:
                dist[nb] = nd
    return max(dist.values()) if dist else 0


def _parse_cpu_range(cpu_list_str):
    cpus = []
    for part in str(cpu_list_str).split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            cpus.extend(range(int(lo), int(hi) + 1))
        else:
            cpus.append(int(part))
    return cpus


def _compute_frame_time(base_rts, assignments, cpus, wake_deps, task_names):
    weights = {}
    for name in task_names:
        if name not in assignments:
            continue
        assigned = _parse_cpu_range(assignments[name])
        cap = cpus[assigned[0]]["capacity"]
        weights[name] = base_rts[name]["avg"] * 1024 / cap
    adj, in_deg = _build_dag(wake_deps, task_names)
    return _longest_path(task_names, adj, in_deg, weights)


def _compute_energy(base_rts, assignments, cpus, task_names):
    energy = 0.0
    for name in task_names:
        if name not in assignments:
            continue
        assigned = _parse_cpu_range(assignments[name])
        cap = cpus[assigned[0]]["capacity"]
        power_w = cpus[assigned[0]]["power_mw"] / 1000.0
        total_runtime_s = (base_rts[name]["total"] * 1024 / cap) / 1e6
        energy += power_w * total_runtime_s
    return energy


@pytest.fixture(scope="module")
def sysfs_cpus():
    return _read_sysfs()


@pytest.fixture(scope="module")
def trace_data():
    return _parse_ftrace()


@pytest.fixture(scope="module")
def base_rts(trace_data, sysfs_cpus):
    tasks, _, _ = trace_data
    return _compute_base_runtimes(tasks, sysfs_cpus)


@pytest.fixture(scope="module")
def requirements():
    with open("/app/data/requirements.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def current_affinity():
    with open("/app/data/affinity.json") as f:
        return json.load(f)


# ==================== Output file existence ====================

class TestOutputFiles:
    def test_topology_exists(self):
        assert os.path.isfile("/app/output/topology.json")

    def test_task_analysis_exists(self):
        assert os.path.isfile("/app/output/task_analysis.json")

    def test_diagnosis_exists(self):
        assert os.path.isfile("/app/output/diagnosis.json")

    def test_affinity_exists(self):
        assert os.path.isfile("/app/output/affinity.json")

    def test_metrics_exists(self):
        assert os.path.isfile("/app/output/metrics.json")


# ==================== Topology parsing ====================

class TestTopology:
    @pytest.fixture(autouse=True)
    def _load(self, sysfs_cpus):
        self.ref = sysfs_cpus
        with open("/app/output/topology.json") as f:
            self.out = json.load(f)

    def test_all_cpus_present(self):
        for cpu_id in self.ref:
            assert str(cpu_id) in self.out["cpus"], \
                "CPU {} missing from topology output".format(cpu_id)

    def test_capacities_correct(self):
        for cpu_id, info in self.ref.items():
            out_cap = self.out["cpus"][str(cpu_id)]["capacity"]
            assert out_cap == info["capacity"], \
                "CPU {} capacity: expected {}, got {}".format(cpu_id, info["capacity"], out_cap)

    def test_power_correct(self):
        for cpu_id, info in self.ref.items():
            out_power = self.out["cpus"][str(cpu_id)]["power_mw"]
            assert out_power == info["power_mw"], \
                "CPU {} power_mw: expected {}, got {}".format(cpu_id, info["power_mw"], out_power)

    def test_at_least_three_core_types(self):
        types = {self.out["cpus"][str(i)]["type"] for i in self.ref}
        assert len(types) >= 3, \
            "Expected at least 3 distinct core types, got {}".format(types)


# ==================== Task analysis ====================

class TestTaskAnalysis:
    @pytest.fixture(autouse=True)
    def _load(self, trace_data):
        self.tasks, self.deps, _ = trace_data
        with open("/app/output/task_analysis.json") as f:
            self.out = json.load(f)

    def test_all_tasks_present(self):
        for name in self.tasks:
            assert name in self.out["tasks"], \
                "Task '{}' missing from task_analysis".format(name)

    def test_runtimes_accurate(self):
        for name, info in self.tasks.items():
            if name not in self.out["tasks"]:
                continue
            out_rt = self.out["tasks"][name]["avg_runtime_us"]
            exp_rt = info["avg_runtime"]
            assert abs(out_rt - exp_rt) < 100.0, \
                "Task '{}' avg_runtime: expected {:.1f}, got {:.1f}".format(name, exp_rt, out_rt)

    def test_key_dependencies_present(self):
        required_deps = {
            ("Input", "GameLoop"), ("GameLoop", "Physics"), ("GameLoop", "AI"),
            ("Physics", "Render"), ("Render", "PostProc"), ("AI", "AIDecide"),
            ("NetRecv", "NetProc"),
        }
        for src, dst in required_deps:
            if dst not in self.out["tasks"]:
                continue
            out_task = self.out["tasks"][dst]
            assert src in out_task.get("depends_on", []), \
                "Task '{}' should list '{}' in depends_on".format(dst, src)

    def test_pids_present(self):
        for name in self.tasks:
            if name not in self.out["tasks"]:
                continue
            assert "pid" in self.out["tasks"][name], \
                "Task '{}' missing pid field".format(name)


# ==================== Diagnosis ====================

class TestDiagnosis:
    @pytest.fixture(autouse=True)
    def _load(self, base_rts, sysfs_cpus, trace_data, current_affinity, requirements):
        tasks, deps, _ = trace_data
        task_names = list(tasks.keys())
        cur_assign = current_affinity["assignments"]

        self.ref_ft = _compute_frame_time(base_rts, cur_assign, sysfs_cpus, deps, task_names)
        self.ref_energy = _compute_energy(base_rts, cur_assign, sysfs_cpus, task_names)
        self.target_ft = requirements["target_frame_time_us"]
        self.budget = requirements["energy_budget_joules"]

        with open("/app/output/diagnosis.json") as f:
            self.out = json.load(f)

    def test_current_frame_time_approximate(self):
        out = self.out["current_frame_time_us"]
        assert abs(out - self.ref_ft) < 500.0, \
            "Current frame time: expected ~{:.1f}, got {:.1f}".format(self.ref_ft, out)

    def test_frame_time_exceeds_target(self):
        assert self.out["current_frame_time_us"] > self.target_ft, \
            "Current frame time should exceed target"

    def test_frame_time_met_false(self):
        assert self.out["frame_time_met"] is False

    def test_current_energy_approximate(self):
        out = self.out["current_energy_joules"]
        assert abs(out - self.ref_energy) < 0.3, \
            "Current energy: expected ~{:.4f}, got {:.4f}".format(self.ref_energy, out)

    def test_target_values_reported(self):
        assert self.out["target_frame_time_us"] == self.target_ft
        assert abs(self.out["energy_budget_joules"] - self.budget) < 0.01


# ==================== Optimized affinity ====================

class TestOptimizedAffinity:
    @pytest.fixture(autouse=True)
    def _load(self, base_rts, sysfs_cpus, trace_data, requirements):
        self.cpus = sysfs_cpus
        self.base_rts = base_rts
        tasks, deps, _ = trace_data
        self.task_names = list(tasks.keys())
        self.deps = deps
        self.target_ft = requirements["target_frame_time_us"]
        self.budget = requirements["energy_budget_joules"]

        with open("/app/output/affinity.json") as f:
            self.out = json.load(f)

    def test_all_tasks_assigned(self):
        for name in self.task_names:
            assert name in self.out["assignments"], \
                "Task '{}' missing from optimized affinity".format(name)

    def test_valid_cpu_ranges(self):
        for name, cpu_list in self.out["assignments"].items():
            assigned = _parse_cpu_range(cpu_list)
            for c in assigned:
                assert c in self.cpus, \
                    "Task '{}' assigned to invalid CPU {}".format(name, c)
            caps = {self.cpus[c]["capacity"] for c in assigned}
            assert len(caps) == 1, \
                "Task '{}' assigned to CPUs with mixed capacities: {}".format(name, caps)

    def test_frame_time_constraint(self):
        ft = _compute_frame_time(
            self.base_rts, self.out["assignments"], self.cpus,
            self.deps, self.task_names)
        assert ft <= self.target_ft, \
            "Optimized frame time {:.1f}us exceeds target {}us".format(ft, self.target_ft)

    def test_energy_constraint(self):
        e = _compute_energy(
            self.base_rts, self.out["assignments"], self.cpus, self.task_names)
        assert e <= self.budget, \
            "Optimized energy {:.4f}J exceeds budget {}J".format(e, self.budget)

    def test_improves_over_current(self):
        with open("/app/data/affinity.json") as f:
            cur = json.load(f)
        cur_ft = _compute_frame_time(
            self.base_rts, cur["assignments"], self.cpus, self.deps, self.task_names)
        new_ft = _compute_frame_time(
            self.base_rts, self.out["assignments"], self.cpus, self.deps, self.task_names)
        assert new_ft < cur_ft, \
            "Optimized FT {:.1f}us not better than current {:.1f}us".format(new_ft, cur_ft)

    def test_not_trivial_all_same(self):
        caps = set()
        for name, cpu_list in self.out["assignments"].items():
            assigned = _parse_cpu_range(cpu_list)
            caps.add(self.cpus[assigned[0]]["capacity"])
        assert len(caps) > 1, \
            "All tasks assigned to same core type is not optimal"


# ==================== Projected metrics ====================

class TestProjectedMetrics:
    @pytest.fixture(autouse=True)
    def _load(self, base_rts, sysfs_cpus, trace_data, requirements):
        self.cpus = sysfs_cpus
        self.base_rts = base_rts
        tasks, deps, _ = trace_data
        self.task_names = list(tasks.keys())
        self.deps = deps
        self.target_ft = requirements["target_frame_time_us"]
        self.budget = requirements["energy_budget_joules"]

        with open("/app/output/affinity.json") as f:
            opt = json.load(f)
        self.assignments = opt["assignments"]

        with open("/app/output/metrics.json") as f:
            self.out = json.load(f)

    def test_frame_time_consistent(self):
        computed = _compute_frame_time(
            self.base_rts, self.assignments, self.cpus, self.deps, self.task_names)
        reported = self.out["projected_frame_time_us"]
        assert abs(reported - computed) < 500.0, \
            "Projected FT {:.1f} inconsistent with computed {:.1f}".format(reported, computed)

    def test_energy_consistent(self):
        computed = _compute_energy(
            self.base_rts, self.assignments, self.cpus, self.task_names)
        reported = self.out["projected_energy_joules"]
        assert abs(reported - computed) < 0.3, \
            "Projected energy {:.4f} inconsistent with computed {:.4f}".format(reported, computed)

    def test_frame_time_met_true(self):
        assert self.out["frame_time_met"] is True

    def test_energy_met_true(self):
        assert self.out["energy_met"] is True

    def test_projected_frame_time_under_target(self):
        assert self.out["projected_frame_time_us"] <= self.target_ft

    def test_projected_energy_under_budget(self):
        assert self.out["projected_energy_joules"] <= self.budget
