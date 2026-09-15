
import csv
import os
import pytest
from collections import defaultdict

INSTANCES_DIR = "/app/instances"
OUTPUT_DIR = "/app/output"

QUALITY_TARGETS = {
    "ft06": 55,
    "la01": 720,
    "la02": 710,
    "la03": 650,
}


def parse_instance(filepath):
    """Parse OR-Library JSP instance file."""
    with open(filepath) as f:
        lines = [line.strip() for line in f if line.strip()]
    tokens = lines[0].split()
    num_jobs = int(tokens[0])
    num_machines = int(tokens[1])
    jobs = []
    for j in range(num_jobs):
        parts = lines[1 + j].split()
        operations = []
        for k in range(num_machines):
            machine = int(parts[2 * k])
            duration = int(parts[2 * k + 1])
            operations.append((machine, duration))
        jobs.append(operations)
    return num_jobs, num_machines, jobs


def parse_schedule(filepath):
    """Parse solver output CSV into a schedule dict."""
    schedule = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            job = int(row["job"])
            operation = int(row["operation"])
            machine = int(row["machine"])
            start = int(float(row["start"]))
            end = int(float(row["end"]))
            schedule[(job, operation)] = (machine, start, end)
    return schedule


@pytest.fixture(params=sorted(QUALITY_TARGETS.keys()))
def instance_name(request):
    return request.param


class TestOutputExists:
    def test_output_file_exists(self, instance_name):
        path = os.path.join(OUTPUT_DIR, f"{instance_name}.csv")
        assert os.path.exists(path), f"Output file {path} not found"


class TestScheduleCompleteness:
    def test_all_operations_present(self, instance_name):
        inst_path = os.path.join(INSTANCES_DIR, f"{instance_name}.txt")
        out_path = os.path.join(OUTPUT_DIR, f"{instance_name}.csv")
        num_jobs, num_machines, jobs = parse_instance(inst_path)
        schedule = parse_schedule(out_path)

        for j in range(num_jobs):
            for op in range(num_machines):
                assert (j, op) in schedule, (
                    f"Missing operation (job={j}, op={op}) in {instance_name}"
                )

        expected_count = num_jobs * num_machines
        assert len(schedule) == expected_count, (
            f"Expected {expected_count} operations, got {len(schedule)}"
        )


class TestScheduleFeasibility:
    def test_correct_machine_assignments(self, instance_name):
        inst_path = os.path.join(INSTANCES_DIR, f"{instance_name}.txt")
        out_path = os.path.join(OUTPUT_DIR, f"{instance_name}.csv")
        num_jobs, num_machines, jobs = parse_instance(inst_path)
        schedule = parse_schedule(out_path)

        for j in range(num_jobs):
            for op in range(num_machines):
                expected_machine, _ = jobs[j][op]
                actual_machine, _, _ = schedule[(j, op)]
                assert actual_machine == expected_machine, (
                    f"Job {j} op {op}: expected machine {expected_machine}, "
                    f"got {actual_machine}"
                )

    def test_correct_processing_durations(self, instance_name):
        inst_path = os.path.join(INSTANCES_DIR, f"{instance_name}.txt")
        out_path = os.path.join(OUTPUT_DIR, f"{instance_name}.csv")
        num_jobs, num_machines, jobs = parse_instance(inst_path)
        schedule = parse_schedule(out_path)

        for j in range(num_jobs):
            for op in range(num_machines):
                _, expected_dur = jobs[j][op]
                _, start, end = schedule[(j, op)]
                actual_dur = end - start
                assert actual_dur == expected_dur, (
                    f"Job {j} op {op}: expected duration {expected_dur}, "
                    f"got {actual_dur} (start={start}, end={end})"
                )

    def test_nonnegative_start_times(self, instance_name):
        out_path = os.path.join(OUTPUT_DIR, f"{instance_name}.csv")
        schedule = parse_schedule(out_path)

        for (j, op), (m, start, end) in schedule.items():
            assert start >= 0, (
                f"Job {j} op {op}: negative start time {start}"
            )

    def test_job_precedence_respected(self, instance_name):
        inst_path = os.path.join(INSTANCES_DIR, f"{instance_name}.txt")
        out_path = os.path.join(OUTPUT_DIR, f"{instance_name}.csv")
        num_jobs, num_machines, _ = parse_instance(inst_path)
        schedule = parse_schedule(out_path)

        for j in range(num_jobs):
            for op in range(1, num_machines):
                _, _, prev_end = schedule[(j, op - 1)]
                _, curr_start, _ = schedule[(j, op)]
                assert curr_start >= prev_end, (
                    f"Job {j} op {op}: starts at {curr_start} but "
                    f"predecessor ends at {prev_end}"
                )

    def test_no_machine_conflicts(self, instance_name):
        inst_path = os.path.join(INSTANCES_DIR, f"{instance_name}.txt")
        out_path = os.path.join(OUTPUT_DIR, f"{instance_name}.csv")
        num_jobs, num_machines, _ = parse_instance(inst_path)
        schedule = parse_schedule(out_path)

        machine_ops = defaultdict(list)
        for (j, op), (m, start, end) in schedule.items():
            machine_ops[m].append((start, end, j, op))

        for m, ops in machine_ops.items():
            ops.sort()
            for i in range(len(ops) - 1):
                s1, e1, j1, op1 = ops[i]
                s2, e2, j2, op2 = ops[i + 1]
                assert s2 >= e1, (
                    f"Machine {m} conflict: job {j1} op {op1} "
                    f"[{s1},{e1}) overlaps with job {j2} op {op2} [{s2},{e2})"
                )


class TestMakespanQuality:
    def test_makespan_within_target(self, instance_name):
        out_path = os.path.join(OUTPUT_DIR, f"{instance_name}.csv")
        schedule = parse_schedule(out_path)

        makespan = max(end for (_, _, end) in schedule.values())
        target = QUALITY_TARGETS[instance_name]

        assert makespan <= target, (
            f"{instance_name}: makespan {makespan} exceeds "
            f"maximum allowed {target}"
        )
