"""Instance loader for n-Queens problem variants.

Supports two problem types:
- QC (n-Queens Completion): JSON format with pre-placed queens
- EDP (Excluded Diagonals Problem): Custom text format with excluded diagonals
"""

import json
import os


def load_qc_instance(filepath):
    """Load an n-Queens Completion instance from JSON.

    Expected format:
        {"n": int, "pre_placed": [[row, col], ...], "id": str}
    """
    with open(filepath) as f:
        data = json.load(f)
    return {
        "n": data["n"],
        "pre_placed": [tuple(q) for q in data["pre_placed"]],
        "id": data["id"],
    }


def load_edp_instance(filepath):
    """Load an Excluded Diagonals Problem instance.

    File format: lines starting with % are comments.
        n=<int>
        D+ = {<comma-separated ints>}   (forward diagonals: r - c = const)
        D- = {<comma-separated ints>}   (backward diagonals: r + c = const)
    """
    n = None
    fwd = []
    bwd = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("%"):
                continue
            if line.startswith("n="):
                n = int(line.split("=")[1].strip())
            elif line.startswith("D+"):
                content = line.split("=", 1)[1].strip().strip("{}")
                if content:
                    fwd = [int(x.strip()) for x in content.split(",")]
            elif line.startswith("D-"):
                content = line.split("=", 1)[1].strip().strip("{}")
                if content:
                    bwd = [int(x.strip()) for x in content.split(",")]

    inst_id = os.path.splitext(os.path.basename(filepath))[0]
    return {"n": n, "excluded_forward": fwd, "excluded_backward": bwd, "id": inst_id}


def write_result(result_dir, inst_id, satisfiable, solution=None):
    """Write a result file in the standard format."""
    os.makedirs(result_dir, exist_ok=True)
    result = {"id": inst_id, "satisfiable": satisfiable, "solution": solution}
    with open(os.path.join(result_dir, f"{inst_id}_result.json"), "w") as f:
        json.dump(result, f, indent=2)
