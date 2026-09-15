
import csv
import json
import os
import pytest

TRACES = ["trace1", "trace2", "trace3", "trace4", "trace5", "trace6"]

EXPECTED = {
    "trace1": {
        "num_steps": 4,
        "num_edges": 4,
        "work": 11,
        "span": 8,
        "parallelism": 1.375,
        "data_races": [],
    },
    "trace2": {
        "num_steps": 4,
        "num_edges": 4,
        "work": 10,
        "span": 7,
        "parallelism": 10.0 / 7.0,
        "data_races": [["r1", "w1"]],
    },
    "trace3": {
        "num_steps": 9,
        "num_edges": 11,
        "work": 25,
        "span": 13,
        "parallelism": 25.0 / 13.0,
        "data_races": [["r1", "w1"], ["r2", "w2"]],
    },
    "trace4": {
        "num_steps": 11,
        "num_edges": 14,
        "work": 26,
        "span": 15,
        "parallelism": 26.0 / 15.0,
        "data_races": [["r1", "w1"], ["r2", "w2"], ["r3", "w3"]],
    },
    "trace5": {
        "num_steps": 7,
        "num_edges": 8,
        "work": 14,
        "span": 10,
        "parallelism": 1.4,
        "data_races": [["r1", "w1"], ["r1", "w2"], ["w1", "w2"]],
    },
    "trace6": {
        "num_steps": 11,
        "num_edges": 14,
        "work": 24,
        "span": 11,
        "parallelism": 24.0 / 11.0,
        "data_races": [["r1", "w1"], ["r2", "w1"], ["r3", "w2"]],
    },
}

EXPECTED_EDGES = {
    "trace1": [(0, 1), (0, 2), (1, 3), (2, 3)],
    "trace2": [(0, 1), (0, 2), (1, 3), (2, 3)],
    "trace3": [
        (0, 1), (1, 2), (1, 3), (2, 4), (3, 4),
        (0, 5), (5, 6), (5, 7), (4, 8), (6, 8), (7, 8),
    ],
    "trace4": [
        (0, 1), (0, 2), (2, 3), (2, 4), (1, 5), (3, 5), (4, 5),
        (5, 6), (5, 7), (7, 8), (7, 9), (6, 10), (8, 10), (9, 10),
    ],
    "trace5": [
        (0, 1), (1, 2), (1, 3), (0, 4), (2, 5), (3, 5), (4, 5), (5, 6),
    ],
    "trace6": [
        (0, 1), (1, 2), (1, 3), (2, 4), (3, 4), (0, 5),
        (5, 6), (6, 7), (6, 8), (5, 9), (4, 10), (7, 10), (8, 10), (9, 10),
    ],
}

EXPECTED_STEP_COSTS = {
    "trace1": {0: 2, 1: 5, 2: 3, 3: 1},
    "trace2": {0: 1, 1: 3, 2: 4, 3: 2},
    "trace3": {0: 2, 1: 1, 2: 6, 3: 2, 4: 3, 5: 4, 6: 5, 7: 1, 8: 1},
    "trace4": {0: 3, 1: 4, 2: 1, 3: 2, 4: 2, 5: 1, 6: 6, 7: 2, 8: 3, 9: 1, 10: 1},
    "trace5": {0: 1, 1: 2, 2: 4, 3: 1, 4: 3, 5: 2, 6: 1},
    "trace6": {0: 2, 1: 1, 2: 5, 3: 3, 4: 2, 5: 1, 6: 4, 7: 2, 8: 1, 9: 2, 10: 1},
}

EXPECTED_MAKESPAN = {
    "trace1": 8,
    "trace2": 7,
    "trace3": 14,
    "trace4": 16,
    "trace5": 10,
    "trace6": 14,
}


# ─── Analysis tests ───


@pytest.fixture(scope="session")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.mark.parametrize("trace", TRACES)
def test_num_steps(results, trace):
    assert results[trace]["num_steps"] == EXPECTED[trace]["num_steps"]


@pytest.mark.parametrize("trace", TRACES)
def test_num_edges(results, trace):
    assert results[trace]["num_edges"] == EXPECTED[trace]["num_edges"]


@pytest.mark.parametrize("trace", TRACES)
def test_work(results, trace):
    assert results[trace]["work"] == EXPECTED[trace]["work"]


@pytest.mark.parametrize("trace", TRACES)
def test_span(results, trace):
    assert results[trace]["span"] == EXPECTED[trace]["span"]


@pytest.mark.parametrize("trace", TRACES)
def test_parallelism(results, trace):
    expected = EXPECTED[trace]["parallelism"]
    actual = results[trace]["parallelism"]
    assert abs(actual - expected) < 1e-4


@pytest.mark.parametrize("trace", TRACES)
def test_data_races(results, trace):
    actual = [sorted(pair) for pair in results[trace]["data_races"]]
    actual.sort()
    expected = EXPECTED[trace]["data_races"]
    assert actual == expected


# ─── Visualization tests ───


@pytest.mark.parametrize("trace", TRACES)
def test_dot_file_exists(trace):
    path = f"/app/graphs/{trace}.dot"
    assert os.path.isfile(path), f"Missing DOT file: {path}"


@pytest.mark.parametrize("trace", TRACES)
def test_png_file_exists(trace):
    path = f"/app/graphs/{trace}.png"
    assert os.path.isfile(path), f"Missing PNG file: {path}"
    assert os.path.getsize(path) > 0, f"PNG file is empty: {path}"


@pytest.mark.parametrize("trace", TRACES)
def test_dot_node_count(trace):
    path = f"/app/graphs/{trace}.dot"
    with open(path) as f:
        content = f.read()
    label_lines = [l for l in content.split("\n") if "label=" in l and "->" not in l]
    expected_nodes = EXPECTED[trace]["num_steps"]
    assert len(label_lines) == expected_nodes, (
        f"{trace}: expected {expected_nodes} node definitions, found {len(label_lines)}"
    )


@pytest.mark.parametrize("trace", TRACES)
def test_dot_edge_count(trace):
    path = f"/app/graphs/{trace}.dot"
    with open(path) as f:
        content = f.read()
    edge_lines = [l for l in content.split("\n") if "->" in l]
    expected_edges = EXPECTED[trace]["num_edges"]
    assert len(edge_lines) == expected_edges, (
        f"{trace}: expected {expected_edges} edges, found {len(edge_lines)}"
    )


@pytest.mark.parametrize("trace", TRACES)
def test_dot_edge_colors(trace):
    path = f"/app/graphs/{trace}.dot"
    with open(path) as f:
        content = f.read()
    assert "red" in content, f"{trace}: DOT missing red (spawn) edges"
    assert "blue" in content, f"{trace}: DOT missing blue (continue) edges"
    assert "green" in content, f"{trace}: DOT missing green (join) edges"


# ─── Schedule tests ───


def _read_schedule(trace):
    path = f"/app/schedules/{trace}.csv"
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "step_id": int(row["step_id"]),
                "processor": int(row["processor"]),
                "start_time": int(row["start_time"]),
                "end_time": int(row["end_time"]),
            })
    return rows


@pytest.mark.parametrize("trace", TRACES)
def test_schedule_csv_exists(trace):
    path = f"/app/schedules/{trace}.csv"
    assert os.path.isfile(path), f"Missing schedule CSV: {path}"


@pytest.mark.parametrize("trace", TRACES)
def test_schedule_step_count(trace):
    rows = _read_schedule(trace)
    expected = EXPECTED[trace]["num_steps"]
    assert len(rows) == expected, (
        f"{trace}: schedule has {len(rows)} rows, expected {expected}"
    )


@pytest.mark.parametrize("trace", TRACES)
def test_schedule_no_processor_overlap(trace):
    rows = _read_schedule(trace)
    by_proc = {}
    for r in rows:
        by_proc.setdefault(r["processor"], []).append(r)
    for pid, tasks in by_proc.items():
        tasks.sort(key=lambda x: x["start_time"])
        for i in range(len(tasks) - 1):
            assert tasks[i]["end_time"] <= tasks[i + 1]["start_time"], (
                f"{trace} P{pid}: step {tasks[i]['step_id']} ends at {tasks[i]['end_time']} "
                f"but step {tasks[i+1]['step_id']} starts at {tasks[i+1]['start_time']}"
            )


@pytest.mark.parametrize("trace", TRACES)
def test_schedule_dependencies(trace):
    rows = _read_schedule(trace)
    end_times = {r["step_id"]: r["end_time"] for r in rows}
    start_times = {r["step_id"]: r["start_time"] for r in rows}
    for u, v in EXPECTED_EDGES[trace]:
        assert end_times[u] <= start_times[v], (
            f"{trace}: edge {u}->{v} violated: step {u} ends at {end_times[u]} "
            f"but step {v} starts at {start_times[v]}"
        )


@pytest.mark.parametrize("trace", TRACES)
def test_schedule_step_durations(trace):
    rows = _read_schedule(trace)
    for r in rows:
        sid = r["step_id"]
        expected_cost = EXPECTED_STEP_COSTS[trace][sid]
        actual_dur = r["end_time"] - r["start_time"]
        assert actual_dur == expected_cost, (
            f"{trace}: step {sid} duration is {actual_dur}, expected cost {expected_cost}"
        )


@pytest.mark.parametrize("trace", TRACES)
def test_schedule_makespan(trace):
    rows = _read_schedule(trace)
    actual_makespan = max(r["end_time"] for r in rows)
    expected = EXPECTED_MAKESPAN[trace]
    assert actual_makespan == expected, (
        f"{trace}: makespan is {actual_makespan}, expected {expected}"
    )


# ─── Summary and report tests ───


@pytest.fixture(scope="session")
def summary():
    with open("/app/schedules/summary.json") as f:
        return json.load(f)


@pytest.mark.parametrize("trace", TRACES)
def test_summary_makespan(summary, trace):
    assert summary[trace]["makespan"] == EXPECTED_MAKESPAN[trace]
    assert summary[trace]["processors"] == 2


@pytest.fixture(scope="session")
def report():
    with open("/app/report.json") as f:
        return json.load(f)


@pytest.mark.parametrize("trace", TRACES)
def test_report_has_analysis(report, trace):
    assert "num_steps" in report[trace]
    assert "work" in report[trace]
    assert "span" in report[trace]
    assert "parallelism" in report[trace]
    assert "data_races" in report[trace]


@pytest.mark.parametrize("trace", TRACES)
def test_report_has_schedule(report, trace):
    assert "makespan" in report[trace]
    assert "processors" in report[trace]
    assert report[trace]["makespan"] == EXPECTED_MAKESPAN[trace]


# ─── Makefile tests ───


def test_makefile_exists():
    assert os.path.isfile("/app/Makefile"), "Missing /app/Makefile"


def test_makefile_targets():
    with open("/app/Makefile") as f:
        content = f.read()
    for target in ["all", "analyze", "visualize", "schedule", "report"]:
        assert target in content, f"Makefile missing target: {target}"
