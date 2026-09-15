"""
"""
import json
import os
import pytest


MAKESPAN_TARGETS = {
    "ft06": 60,
    "la01": 750,
    "ft10": 1080,
    "ft20": 1350,
    "abz7": 900,
}

INSTANCE_NAMES = list(MAKESPAN_TARGETS.keys())


def parse_jsp_instance(filepath):
    """Parse an OR-Library JSP instance file."""
    with open(filepath) as f:
        lines = [line.strip() for line in f if line.strip()]
    n_jobs, n_machines = map(int, lines[0].split())
    jobs = []
    for i in range(1, n_jobs + 1):
        vals = list(map(int, lines[i].split()))
        operations = []
        for j in range(0, len(vals), 2):
            operations.append((vals[j], vals[j + 1]))  # (machine, duration)
        jobs.append(operations)
    return n_jobs, n_machines, jobs


@pytest.fixture(scope="session")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def instances():
    data = {}
    for name in INSTANCE_NAMES:
        path = f"/app/data/{name}.txt"
        n_jobs, n_machines, jobs = parse_jsp_instance(path)
        data[name] = {"n_jobs": n_jobs, "n_machines": n_machines, "jobs": jobs}
    return data


class TestResultsExistAndComplete:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "/app/results.json not found"

    @pytest.mark.parametrize("name", INSTANCE_NAMES)
    def test_instance_present(self, results, name):
        assert name in results, f"Instance '{name}' missing from results"

    @pytest.mark.parametrize("name", INSTANCE_NAMES)
    def test_has_makespan_field(self, results, name):
        assert "makespan" in results[name], f"'{name}' missing 'makespan'"
        assert isinstance(results[name]["makespan"], int), f"'{name}' makespan must be int"

    @pytest.mark.parametrize("name", INSTANCE_NAMES)
    def test_has_schedule_field(self, results, name):
        assert "schedule" in results[name], f"'{name}' missing 'schedule'"
        assert isinstance(results[name]["schedule"], dict), f"'{name}' schedule must be dict"


class TestScheduleStructure:
    @pytest.mark.parametrize("name", INSTANCE_NAMES)
    def test_correct_number_of_jobs(self, results, instances, name):
        n_jobs = instances[name]["n_jobs"]
        schedule = results[name]["schedule"]
        assert len(schedule) == n_jobs, (
            f"{name}: expected {n_jobs} jobs, got {len(schedule)}"
        )

    @pytest.mark.parametrize("name", INSTANCE_NAMES)
    def test_correct_operations_per_job(self, results, instances, name):
        jobs = instances[name]["jobs"]
        schedule = results[name]["schedule"]
        for job_idx, job_ops in enumerate(jobs):
            key = str(job_idx)
            assert key in schedule, f"{name}: job {job_idx} missing"
            sched_ops = schedule[key]
            assert len(sched_ops) == len(job_ops), (
                f"{name} job {job_idx}: expected {len(job_ops)} ops, got {len(sched_ops)}"
            )

    @pytest.mark.parametrize("name", INSTANCE_NAMES)
    def test_correct_machine_and_duration(self, results, instances, name):
        jobs = instances[name]["jobs"]
        schedule = results[name]["schedule"]
        for job_idx, job_ops in enumerate(jobs):
            sched_ops = schedule[str(job_idx)]
            for op_idx, (exp_machine, exp_dur) in enumerate(job_ops):
                op = sched_ops[op_idx]
                assert op["machine"] == exp_machine, (
                    f"{name} job {job_idx} op {op_idx}: "
                    f"expected machine {exp_machine}, got {op['machine']}"
                )
                assert op["duration"] == exp_dur, (
                    f"{name} job {job_idx} op {op_idx}: "
                    f"expected duration {exp_dur}, got {op['duration']}"
                )


class TestFeasibility:
    @pytest.mark.parametrize("name", INSTANCE_NAMES)
    def test_nonnegative_start_times(self, results, instances, name):
        schedule = results[name]["schedule"]
        n_jobs = instances[name]["n_jobs"]
        for job_idx in range(n_jobs):
            for op_idx, op in enumerate(schedule[str(job_idx)]):
                assert op["start"] >= 0, (
                    f"{name} job {job_idx} op {op_idx}: "
                    f"negative start time {op['start']}"
                )

    @pytest.mark.parametrize("name", INSTANCE_NAMES)
    def test_precedence_constraints(self, results, instances, name):
        """Each operation must start after the previous one in the same job ends."""
        schedule = results[name]["schedule"]
        n_jobs = instances[name]["n_jobs"]
        for job_idx in range(n_jobs):
            ops = schedule[str(job_idx)]
            for op_idx in range(1, len(ops)):
                prev_end = ops[op_idx - 1]["start"] + ops[op_idx - 1]["duration"]
                curr_start = ops[op_idx]["start"]
                assert curr_start >= prev_end, (
                    f"{name} job {job_idx}: op {op_idx} starts at {curr_start} "
                    f"but previous op ends at {prev_end}"
                )

    @pytest.mark.parametrize("name", INSTANCE_NAMES)
    def test_no_machine_overlap(self, results, instances, name):
        """No two operations on the same machine may overlap in time."""
        schedule = results[name]["schedule"]
        n_jobs = instances[name]["n_jobs"]
        machine_intervals = {}
        for job_idx in range(n_jobs):
            for op_idx, op in enumerate(schedule[str(job_idx)]):
                m = op["machine"]
                start = op["start"]
                end = start + op["duration"]
                machine_intervals.setdefault(m, []).append(
                    (start, end, job_idx, op_idx)
                )
        for machine, intervals in machine_intervals.items():
            intervals.sort()
            for i in range(len(intervals) - 1):
                _, end_a, job_a, op_a = intervals[i]
                start_b, _, job_b, op_b = intervals[i + 1]
                assert start_b >= end_a, (
                    f"{name} machine {machine}: "
                    f"job {job_a} op {op_a} ends at {end_a}, "
                    f"job {job_b} op {op_b} starts at {start_b}"
                )


class TestMakespan:
    @pytest.mark.parametrize("name", INSTANCE_NAMES)
    def test_reported_makespan_matches_schedule(self, results, instances, name):
        """The reported makespan must equal the actual latest completion time."""
        schedule = results[name]["schedule"]
        n_jobs = instances[name]["n_jobs"]
        actual = 0
        for job_idx in range(n_jobs):
            for op in schedule[str(job_idx)]:
                actual = max(actual, op["start"] + op["duration"])
        reported = results[name]["makespan"]
        assert reported == actual, (
            f"{name}: reported makespan {reported} != actual {actual}"
        )

    @pytest.mark.parametrize("name,target", list(MAKESPAN_TARGETS.items()))
    def test_makespan_within_target(self, results, name, target):
        """Makespan must not exceed the required target."""
        makespan = results[name]["makespan"]
        assert makespan <= target, (
            f"{name}: makespan {makespan} exceeds target {target}"
        )
