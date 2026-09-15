
import json
import os
import sqlite3
import pytest

# === Ground-truth test outputs ===

EXPECTED = {
    "arc_task_007bbfb7": [
        [[7, 0, 7, 0, 0, 0, 7, 0, 7], [7, 0, 7, 0, 0, 0, 7, 0, 7],
         [7, 7, 0, 0, 0, 0, 7, 7, 0], [7, 0, 7, 0, 0, 0, 7, 0, 7],
         [7, 0, 7, 0, 0, 0, 7, 0, 7], [7, 7, 0, 0, 0, 0, 7, 7, 0],
         [7, 0, 7, 7, 0, 7, 0, 0, 0], [7, 0, 7, 7, 0, 7, 0, 0, 0],
         [7, 7, 0, 7, 7, 0, 0, 0, 0]]
    ],
    "arc2_task_00576224": [
        [[3, 2, 3, 2, 3, 2], [7, 8, 7, 8, 7, 8],
         [2, 3, 2, 3, 2, 3], [8, 7, 8, 7, 8, 7],
         [3, 2, 3, 2, 3, 2], [7, 8, 7, 8, 7, 8]]
    ],
    "arc_task_0520fde7": [
        [[2, 0, 2], [0, 0, 0], [0, 0, 0]]
    ],
    "arc_task_00d62c1b": [
        [[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 3, 4, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 3, 0, 3, 3, 3, 3, 3, 0, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 3, 4, 4, 4, 4, 3, 4, 4, 3, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 3, 3, 3, 3, 3, 0, 3, 3, 3, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 3, 3, 3, 3, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 4, 4, 4, 3, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 4, 4, 4, 3, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 3, 3, 3, 3, 4, 4, 4, 3, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 4, 4, 4, 3, 4, 4, 4, 3, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 3, 3, 3, 3, 3, 3, 4, 4, 4, 3, 0, 0],
         [0, 0, 0, 0, 0, 0, 3, 3, 4, 3, 0, 0, 0, 3, 3, 3, 3, 3, 0, 0],
         [0, 0, 3, 0, 0, 0, 0, 0, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 3, 4, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 3, 0, 3, 0, 3, 3, 3, 3, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 3, 4, 4, 4, 3, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 3, 4, 4, 4, 3, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 3, 3, 3, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]]
    ],
    "arc_task_017c7c7b": [
        [[2, 2, 2], [0, 2, 0], [0, 2, 0],
         [2, 2, 2], [0, 2, 0], [0, 2, 0],
         [2, 2, 2], [0, 2, 0], [0, 2, 0]]
    ],
    "arc2_task_00dbd492": [
        [[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 0, 0, 0, 0],
         [0, 2, 2, 2, 2, 2, 2, 2, 2, 2, 0, 2, 8, 8, 8, 2, 0, 0, 0, 0],
         [0, 2, 3, 3, 3, 3, 3, 3, 3, 2, 0, 2, 8, 2, 8, 2, 0, 0, 0, 0],
         [0, 2, 3, 3, 3, 3, 3, 3, 3, 2, 0, 2, 8, 8, 8, 2, 0, 0, 0, 0],
         [0, 2, 3, 3, 3, 3, 3, 3, 3, 2, 0, 2, 2, 2, 2, 2, 0, 0, 0, 0],
         [0, 2, 3, 3, 3, 2, 3, 3, 3, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 2, 3, 3, 3, 3, 3, 3, 3, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 2, 3, 3, 3, 3, 3, 3, 3, 2, 0, 0, 0, 2, 2, 2, 2, 2, 0, 0],
         [0, 2, 3, 3, 3, 3, 3, 3, 3, 2, 0, 0, 0, 2, 8, 8, 8, 2, 0, 0],
         [0, 2, 2, 2, 2, 2, 2, 2, 2, 2, 0, 0, 0, 2, 8, 2, 8, 2, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 8, 8, 8, 2, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 0, 0],
         [0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 2, 4, 4, 4, 4, 4, 2, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 2, 4, 4, 4, 4, 4, 2, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 2, 4, 4, 2, 4, 4, 2, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 2, 4, 4, 4, 4, 4, 2, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 2, 4, 4, 4, 4, 4, 2, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]]
    ],
}

# Expected metadata for solve_log table
EXPECTED_METADATA = {
    "arc_task_007bbfb7": {
        "input_rows": 3, "input_cols": 3,
        "output_rows": 9, "output_cols": 9, "num_colors": 2,
    },
    "arc2_task_00576224": {
        "input_rows": 2, "input_cols": 2,
        "output_rows": 6, "output_cols": 6, "num_colors": 4,
    },
    "arc_task_0520fde7": {
        "input_rows": 3, "input_cols": 7,
        "output_rows": 3, "output_cols": 3, "num_colors": 2,
    },
    "arc_task_00d62c1b": {
        "input_rows": 20, "input_cols": 20,
        "output_rows": 20, "output_cols": 20, "num_colors": 3,
    },
    "arc_task_017c7c7b": {
        "input_rows": 6, "input_cols": 3,
        "output_rows": 9, "output_cols": 3, "num_colors": 2,
    },
    "arc2_task_00dbd492": {
        "input_rows": 20, "input_cols": 20,
        "output_rows": 20, "output_cols": 20, "num_colors": 5,
    },
}

# Expected PNG dimensions (width, height) = (cols*20, rows*20)
EXPECTED_VIZ_DIMS = {
    "arc_task_007bbfb7": (180, 180),
    "arc2_task_00576224": (120, 120),
    "arc_task_0520fde7": (60, 60),
    "arc_task_00d62c1b": (400, 400),
    "arc_task_017c7c7b": (60, 180),
    "arc2_task_00dbd492": (400, 400),
}

DB_PATH = "/app/pipeline.db"
TASK_IDS = list(EXPECTED.keys())


def load_output(task_id):
    path = f"/app/outputs/{task_id}.json"
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


# ---- Grid correctness tests ----

@pytest.mark.parametrize("task_id", TASK_IDS)
def test_output_file_exists(task_id):
    path = f"/app/outputs/{task_id}.json"
    assert os.path.exists(path), f"Output file missing: {path}"


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_output_has_correct_structure(task_id):
    data = load_output(task_id)
    assert data is not None, f"Could not load output for {task_id}"
    assert "test_outputs" in data, f"Missing 'test_outputs' key in {task_id}"
    expected_count = len(EXPECTED[task_id])
    actual_count = len(data["test_outputs"])
    assert actual_count == expected_count, (
        f"{task_id}: expected {expected_count} test outputs, got {actual_count}"
    )


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_output_grids_match(task_id):
    data = load_output(task_id)
    assert data is not None
    for i, (actual, expected) in enumerate(
        zip(data["test_outputs"], EXPECTED[task_id])
    ):
        assert len(actual) == len(expected), (
            f"{task_id} test {i}: row count mismatch "
            f"(got {len(actual)}, expected {len(expected)})"
        )
        for r, (a_row, e_row) in enumerate(zip(actual, expected)):
            assert len(a_row) == len(e_row), (
                f"{task_id} test {i} row {r}: col count mismatch "
                f"(got {len(a_row)}, expected {len(e_row)})"
            )
            assert a_row == e_row, (
                f"{task_id} test {i} row {r}: grid mismatch\n"
                f"  got:      {a_row}\n"
                f"  expected: {e_row}"
            )


# ---- Database tests ----

def test_submissions_table_has_all_tasks():
    """Verify all 6 tasks were submitted via the API (submissions table populated)."""
    assert os.path.exists(DB_PATH), f"Database missing: {DB_PATH}"
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT task_id FROM submissions ORDER BY task_id"
    ).fetchall()
    conn.close()
    submitted = {r[0] for r in rows}
    for task_id in TASK_IDS:
        assert task_id in submitted, (
            f"Task {task_id} not found in submissions table "
            f"(was it submitted via the API?)"
        )


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_solve_log_metadata(task_id):
    """Verify solve_log has correct metadata for each task."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT input_rows, input_cols, output_rows, output_cols, "
        "num_colors, transformation_type FROM solve_log WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    conn.close()
    assert row is not None, f"solve_log missing entry for {task_id}"
    actual = {
        "input_rows": row[0], "input_cols": row[1],
        "output_rows": row[2], "output_cols": row[3],
        "num_colors": row[4],
    }
    expected_meta = EXPECTED_METADATA[task_id]
    for key, val in expected_meta.items():
        assert actual[key] == val, (
            f"{task_id} solve_log.{key}: expected {val}, got {actual[key]}"
        )
    transformation_type = row[5]
    assert transformation_type and len(transformation_type.strip()) > 0, (
        f"{task_id}: transformation_type must be non-empty"
    )


# ---- Visualization tests ----

@pytest.mark.parametrize("task_id", TASK_IDS)
def test_visualization_exists(task_id):
    path = f"/app/visualizations/{task_id}_test_0.png"
    assert os.path.exists(path), f"Visualization missing: {path}"


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_visualization_dimensions(task_id):
    """Verify PNG pixel dimensions match expected grid size * 20px."""
    from PIL import Image
    path = f"/app/visualizations/{task_id}_test_0.png"
    if not os.path.exists(path):
        pytest.skip(f"PNG not found: {path}")
    img = Image.open(path)
    w, h = img.size
    exp_w, exp_h = EXPECTED_VIZ_DIMS[task_id]
    assert w == exp_w, (
        f"{task_id}: expected PNG width {exp_w}, got {w}"
    )
    assert h == exp_h, (
        f"{task_id}: expected PNG height {exp_h}, got {h}"
    )
