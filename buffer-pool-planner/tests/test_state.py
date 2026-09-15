
import json
import subprocess
import pytest


def run_planner(graph, test_id="default"):
    """Write graph, run planner, return parsed solution."""
    graph_path = "/app/test_graph_{}.json".format(test_id)
    solution_path = "/app/test_solution_{}.json".format(test_id)

    with open(graph_path, "w") as f:
        json.dump(graph, f, indent=2)

    result = subprocess.run(
        ["python3", "/app/buffer_planner.py", graph_path, solution_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "Planner failed (exit {}):\nstdout: {}\nstderr: {}".format(
            result.returncode, result.stdout, result.stderr)
    )

    with open(solution_path) as f:
        return json.load(f)


def validate_solution(graph, solution):
    """Validate correctness of a solution. Returns pool_sizes dict."""
    ops = {op["id"]: op for op in graph["operations"]}
    schedule = solution["schedule"]
    assignments = solution["assignments"]
    pool_sizes = solution["pool_sizes"]
    buffers = graph["buffers"]

    # --- schedule completeness ---
    assert set(schedule) == set(ops.keys()), (
        "Schedule ops mismatch: expected {}, got {}".format(
            sorted(ops.keys()), sorted(schedule))
    )
    assert len(schedule) == len(set(schedule)), "Duplicate ops in schedule"

    # --- topological validity ---
    pos = {op_id: i for i, op_id in enumerate(schedule)}
    for op in graph["operations"]:
        for dep in op["deps"]:
            assert pos[dep] < pos[op["id"]], (
                "Topological violation: {} (step {}) must precede {} (step {})".format(
                    dep, pos[dep], op["id"], pos[op["id"]]))

    # --- all buffers assigned ---
    for buf_id in buffers:
        assert buf_id in assignments, "Buffer {} missing from assignments".format(buf_id)

    # --- non-negative offsets ---
    for buf_id, offset in assignments.items():
        if buf_id in buffers:
            assert offset >= 0, "Buffer {} has negative offset {}".format(buf_id, offset)

    # --- compute lifetimes ---
    alloc_step = {}
    dealloc_step = {}
    for op in graph["operations"]:
        step = pos[op["id"]]
        for b in op.get("allocs", []):
            if b in buffers:
                alloc_step[b] = step
        for b in op.get("deallocs", []):
            if b in buffers:
                dealloc_step[b] = step

    for buf_id in buffers:
        assert buf_id in alloc_step, "Buffer {} never allocated".format(buf_id)
        assert buf_id in dealloc_step, "Buffer {} never deallocated".format(buf_id)
        assert alloc_step[buf_id] <= dealloc_step[buf_id], (
            "Buffer {}: alloc step {} > dealloc step {}".format(
                buf_id, alloc_step[buf_id], dealloc_step[buf_id]))

    # --- no memory overlap for conflicting buffers ---
    buf_ids = list(buffers.keys())
    for i in range(len(buf_ids)):
        for j in range(i + 1, len(buf_ids)):
            bi, bj = buf_ids[i], buf_ids[j]
            if buffers[bi]["memory_space"] != buffers[bj]["memory_space"]:
                continue
            ai, di = alloc_step[bi], dealloc_step[bi]
            aj, dj = alloc_step[bj], dealloc_step[bj]
            if ai <= dj and aj <= di:  # lifetimes overlap
                oi = assignments[bi]
                si = buffers[bi]["size"]
                oj = assignments[bj]
                sj = buffers[bj]["size"]
                assert oi + si <= oj or oj + sj <= oi, (
                    "Conflicting buffers {} [{},{}) and {} [{},{}) overlap in memory "
                    "(lifetimes [{},{}] and [{},{}])".format(
                        bi, oi, oi + si, bj, oj, oj + sj, ai, di, aj, dj))

    # --- alignment ---
    for buf_id, buf in buffers.items():
        align = buf["alignment"]
        assert assignments[buf_id] % align == 0, (
            "Buffer {} at offset {} not aligned to {}".format(
                buf_id, assignments[buf_id], align))

    # --- pool sizes contain all spaces ---
    for buf_id, buf in buffers.items():
        space = buf["memory_space"]
        assert space in pool_sizes, "Memory space '{}' not in pool_sizes".format(space)
        assert assignments[buf_id] + buf["size"] <= pool_sizes[space], (
            "Buffer {} ends at {} but pool '{}' size is {}".format(
                buf_id, assignments[buf_id] + buf["size"], space, pool_sizes[space]))

    # --- pool sizes are tight ---
    for space in pool_sizes:
        max_end = 0
        for buf_id, buf in buffers.items():
            if buf["memory_space"] == space:
                end = assignments[buf_id] + buf["size"]
                if end > max_end:
                    max_end = end
        assert pool_sizes[space] == max_end, (
            "Pool '{}' size should be {}, got {}".format(
                space, max_end, pool_sizes[space]))

    return pool_sizes


# -- Test 1: Sequential non-overlapping buffers should share pool --


class TestSequentialReuse:
    def test_correctness_and_quality(self):
        graph = {
            "buffers": {
                "A": {"size": 4096, "alignment": 64, "memory_space": "global"},
                "B": {"size": 2048, "alignment": 64, "memory_space": "global"},
            },
            "views": {},
            "operations": [
                {"id": "op0", "deps": [], "allocs": ["A"], "uses": [], "deallocs": []},
                {"id": "op1", "deps": ["op0"], "allocs": [], "uses": ["A"], "deallocs": []},
                {"id": "op2", "deps": ["op1"], "allocs": [], "uses": [], "deallocs": ["A"]},
                {"id": "op3", "deps": ["op2"], "allocs": ["B"], "uses": [], "deallocs": []},
                {"id": "op4", "deps": ["op3"], "allocs": [], "uses": ["B"], "deallocs": []},
                {"id": "op5", "deps": ["op4"], "allocs": [], "uses": [], "deallocs": ["B"]},
            ],
        }
        solution = run_planner(graph, "sequential")
        pool_sizes = validate_solution(graph, solution)
        assert pool_sizes["global"] <= 4096, (
            "Sequential non-overlapping buffers should reuse space. "
            "Got pool {}, expected <= 4096".format(pool_sizes["global"]))


# -- Test 2: Overlapping lifetimes cannot share pool --


class TestOverlapping:
    def test_correctness_and_quality(self):
        graph = {
            "buffers": {
                "A": {"size": 4096, "alignment": 64, "memory_space": "global"},
                "B": {"size": 4096, "alignment": 64, "memory_space": "global"},
            },
            "views": {},
            "operations": [
                {"id": "op0", "deps": [], "allocs": ["A"], "uses": [], "deallocs": []},
                {"id": "op1", "deps": ["op0"], "allocs": ["B"], "uses": ["A"], "deallocs": []},
                {"id": "op2", "deps": ["op1"], "allocs": [], "uses": ["A", "B"], "deallocs": []},
                {"id": "op3", "deps": ["op2"], "allocs": [], "uses": [], "deallocs": ["A", "B"]},
            ],
        }
        solution = run_planner(graph, "overlapping")
        pool_sizes = validate_solution(graph, solution)
        assert pool_sizes["global"] == 8192, (
            "Overlapping buffers need separate space. Got {}, expected 8192".format(
                pool_sizes["global"]))


# -- Test 3: Scheduling independent branches to minimize peak memory --


class TestSchedulingImpact:
    def test_correctness_and_quality(self):
        graph = {
            "buffers": {
                "X": {"size": 8192, "alignment": 64, "memory_space": "global"},
                "Y": {"size": 8192, "alignment": 64, "memory_space": "global"},
            },
            "views": {},
            "operations": [
                {"id": "alloc_x", "deps": [], "allocs": ["X"], "uses": [], "deallocs": []},
                {"id": "alloc_y", "deps": [], "allocs": ["Y"], "uses": [], "deallocs": []},
                {"id": "use_x", "deps": ["alloc_x"], "allocs": [], "uses": ["X"], "deallocs": []},
                {"id": "use_y", "deps": ["alloc_y"], "allocs": [], "uses": ["Y"], "deallocs": []},
                {"id": "free_x", "deps": ["use_x"], "allocs": [], "uses": [], "deallocs": ["X"]},
                {"id": "free_y", "deps": ["use_y"], "allocs": [], "uses": [], "deallocs": ["Y"]},
                {"id": "done", "deps": ["free_x", "free_y"], "allocs": [], "uses": [], "deallocs": []},
            ],
        }
        solution = run_planner(graph, "scheduling")
        pool_sizes = validate_solution(graph, solution)
        assert pool_sizes["global"] <= 8192, (
            "Independent branches should be serialized. "
            "Got {}, expected <= 8192".format(pool_sizes["global"]))


# -- Test 4: Buffer views handled correctly --


class TestViews:
    def test_correctness_and_quality(self):
        graph = {
            "buffers": {
                "A": {"size": 8192, "alignment": 256, "memory_space": "global"},
                "B": {"size": 4096, "alignment": 64, "memory_space": "global"},
            },
            "views": {
                "V1": {"parent": "A", "offset": 0, "size": 4096},
                "V2": {"parent": "A", "offset": 4096, "size": 4096},
            },
            "operations": [
                {"id": "op0", "deps": [], "allocs": ["A"], "uses": [], "deallocs": []},
                {"id": "op1", "deps": ["op0"], "allocs": [], "uses": ["V1"], "deallocs": []},
                {"id": "op2", "deps": ["op1"], "allocs": [], "uses": ["V2"], "deallocs": []},
                {"id": "op3", "deps": ["op2"], "allocs": [], "uses": [], "deallocs": ["A"]},
                {"id": "op4", "deps": ["op3"], "allocs": ["B"], "uses": [], "deallocs": []},
                {"id": "op5", "deps": ["op4"], "allocs": [], "uses": ["B"], "deallocs": ["B"]},
            ],
        }
        solution = run_planner(graph, "views")
        pool_sizes = validate_solution(graph, solution)
        assert pool_sizes["global"] <= 8192, (
            "Buffers A and B are non-overlapping (sequential). "
            "Got {}, expected <= 8192".format(pool_sizes["global"]))


# -- Test 5: Multiple independent memory spaces --


class TestMultiSpace:
    def test_correctness_and_quality(self):
        graph = {
            "buffers": {
                "G1": {"size": 4096, "alignment": 64, "memory_space": "global"},
                "G2": {"size": 4096, "alignment": 64, "memory_space": "global"},
                "S1": {"size": 2048, "alignment": 64, "memory_space": "shared"},
                "S2": {"size": 2048, "alignment": 64, "memory_space": "shared"},
            },
            "views": {},
            "operations": [
                {"id": "op0", "deps": [], "allocs": ["G1", "S1"], "uses": [], "deallocs": []},
                {"id": "op1", "deps": ["op0"], "allocs": [], "uses": ["G1", "S1"], "deallocs": ["G1", "S1"]},
                {"id": "op2", "deps": ["op1"], "allocs": ["G2", "S2"], "uses": [], "deallocs": []},
                {"id": "op3", "deps": ["op2"], "allocs": [], "uses": ["G2", "S2"], "deallocs": ["G2", "S2"]},
            ],
        }
        solution = run_planner(graph, "multispace")
        pool_sizes = validate_solution(graph, solution)
        assert pool_sizes["global"] <= 4096, (
            "Global: sequential reuse expected. Got {}".format(pool_sizes["global"]))
        assert pool_sizes["shared"] <= 2048, (
            "Shared: sequential reuse expected. Got {}".format(pool_sizes["shared"]))


# -- Test 6: Optimal alignment packing --
# Designed so first-fit-decreasing gives pool=242 but optimal gives pool=228.
# A(100, align 64), B(50, align 128), C(50, align 64), all simultaneously live.
# FFD places: A@0[0,100), B@128[128,178), C@192[192,242) => pool=242
# Optimal:    B@0[0,50),  C@64[64,114),  A@128[128,228) => pool=228


class TestOptimalAlignment:
    def test_optimal_packing(self):
        graph = {
            "buffers": {
                "A": {"size": 100, "alignment": 64, "memory_space": "global"},
                "B": {"size": 50, "alignment": 128, "memory_space": "global"},
                "C": {"size": 50, "alignment": 64, "memory_space": "global"},
            },
            "views": {},
            "operations": [
                {"id": "op0", "deps": [], "allocs": ["A", "B", "C"], "uses": [], "deallocs": []},
                {"id": "op1", "deps": ["op0"], "allocs": [], "uses": ["A", "B", "C"], "deallocs": ["A", "B", "C"]},
            ],
        }
        solution = run_planner(graph, "opt_align")
        pool_sizes = validate_solution(graph, solution)
        assert pool_sizes["global"] <= 228, (
            "Optimal alignment packing should achieve pool size 228. "
            "Got {} (greedy heuristics typically give 242).".format(pool_sizes["global"]))


# -- Test 7: Complex branching pipeline --


class TestComplexPipeline:
    def test_correctness_and_quality(self):
        graph = {
            "buffers": {
                "input": {"size": 32768, "alignment": 256, "memory_space": "global"},
                "branch_a": {"size": 16384, "alignment": 64, "memory_space": "global"},
                "branch_b": {"size": 16384, "alignment": 64, "memory_space": "global"},
                "proc_a": {"size": 8192, "alignment": 128, "memory_space": "global"},
                "proc_b": {"size": 8192, "alignment": 128, "memory_space": "global"},
                "result": {"size": 4096, "alignment": 64, "memory_space": "global"},
            },
            "views": {},
            "operations": [
                {"id": "op_alloc_input", "deps": [], "allocs": ["input"], "uses": [], "deallocs": []},
                {"id": "op_branch_a", "deps": ["op_alloc_input"], "allocs": ["branch_a"], "uses": ["input"], "deallocs": []},
                {"id": "op_branch_b", "deps": ["op_alloc_input"], "allocs": ["branch_b"], "uses": ["input"], "deallocs": []},
                {"id": "op_free_input", "deps": ["op_branch_a", "op_branch_b"], "allocs": [], "uses": [], "deallocs": ["input"]},
                {"id": "op_proc_a", "deps": ["op_branch_a"], "allocs": ["proc_a"], "uses": ["branch_a"], "deallocs": []},
                {"id": "op_free_ba", "deps": ["op_proc_a"], "allocs": [], "uses": [], "deallocs": ["branch_a"]},
                {"id": "op_proc_b", "deps": ["op_branch_b"], "allocs": ["proc_b"], "uses": ["branch_b"], "deallocs": []},
                {"id": "op_free_bb", "deps": ["op_proc_b"], "allocs": [], "uses": [], "deallocs": ["branch_b"]},
                {
                    "id": "op_join",
                    "deps": ["op_free_input", "op_free_ba", "op_free_bb"],
                    "allocs": ["result"],
                    "uses": ["proc_a", "proc_b"],
                    "deallocs": ["proc_a", "proc_b"],
                },
                {"id": "op_output", "deps": ["op_join"], "allocs": [], "uses": ["result"], "deallocs": ["result"]},
            ],
        }
        solution = run_planner(graph, "complex")
        pool_sizes = validate_solution(graph, solution)
        # Optimal: serialize branches, pack non-interfering buffers.
        # Peak live = 57344 (input + one branch + one proc).
        # With optimal packing, non-interfering buffers share offsets => pool = 57344.
        assert pool_sizes["global"] <= 57344, (
            "Complex pipeline requires good scheduling + optimal packing. "
            "Got {}, expected <= 57344".format(pool_sizes["global"]))
