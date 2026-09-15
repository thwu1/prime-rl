
import json
import math
import os
import sqlite3
import struct

import pytest


def normalize_angle(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a <= -math.pi:
        a += 2 * math.pi
    return a


@pytest.fixture
def result():
    path = "/app/result.json"
    assert os.path.exists(path), "result.json not found at /app/result.json"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, list), "result.json must contain a JSON array"
    assert len(data) == 20, f"Expected 20 nodes, got {len(data)}"
    data.sort(key=lambda n: n["id"])
    return data


@pytest.fixture
def pose_graph():
    conn = sqlite3.connect("/app/pose_graph.db")
    c = conn.cursor()

    nodes = []
    for row in c.execute("SELECT id, x, y, theta FROM nodes ORDER BY id"):
        nodes.append({"id": row[0], "x": row[1], "y": row[2], "theta": row[3]})

    edges = []
    for row in c.execute(
        "SELECT from_id, to_id, dx, dy, dtheta, info_matrix, edge_type FROM edges"
    ):
        info = list(struct.unpack('<6d', row[5]))
        edges.append({
            "from_id": row[0], "to_id": row[1],
            "dx": row[2], "dy": row[3], "dtheta": row[4],
            "information": info, "type": row[6],
        })

    conn.close()
    return {"nodes": nodes, "edges": edges}


def test_result_structure(result):
    """All 20 nodes must have id, x, y, theta fields."""
    for i, node in enumerate(result):
        assert node["id"] == i, f"Node at index {i} has id {node.get('id')}"
        for key in ("x", "y", "theta"):
            assert key in node, f"Node {i} missing '{key}'"
            assert isinstance(node[key], (int, float)), f"Node {i} {key} not numeric"


def test_finite_values(result):
    """No NaN or Inf values."""
    for node in result:
        for key in ("x", "y", "theta"):
            assert math.isfinite(node[key]), f"Node {node['id']} has non-finite {key}"


def test_node_0_anchored(result):
    """Node 0 must stay near its initial position (gauge anchor)."""
    n = result[0]
    assert abs(n["x"]) < 0.1, f"Node 0 x={n['x']:.4f}, expected ~0"
    assert abs(n["y"]) < 0.1, f"Node 0 y={n['y']:.4f}, expected ~0"
    assert abs(normalize_angle(n["theta"])) < 0.1, f"Node 0 theta not ~0"


def test_trajectory_x_extent(result):
    """Trajectory must span a significant x range (robot went out ~45m and back)."""
    xs = [n["x"] for n in result]
    extent = max(xs) - min(xs)
    assert extent > 30.0, (
        f"X extent {extent:.1f}m too small (expected >30m for a 45m out-and-back)"
    )


def test_trajectory_y_bounded(result):
    """All nodes should stay near y=0 (the trajectory is along the x-axis)."""
    for node in result:
        assert abs(node["y"]) < 6.0, (
            f"Node {node['id']} at y={node['y']:.2f}, expected near 0"
        )


def test_forward_headings(result):
    """Forward-leg nodes (0-9) should have heading near 0."""
    for i in range(10):
        h = abs(normalize_angle(result[i]["theta"]))
        assert h < 0.5, (
            f"Node {i} heading {result[i]['theta']:.3f}, expected near 0"
        )


def test_return_headings(result):
    """Return-leg nodes (10-19) should have heading near pi."""
    for i in range(10, 20):
        h = abs(normalize_angle(result[i]["theta"] - math.pi))
        assert h < 0.5, (
            f"Node {i} heading {result[i]['theta']:.3f}, expected near pi"
        )


def _compute_lc_residual(result, fi, ti, edge):
    """Compute position residual for a loop closure edge."""
    ni = result[fi]
    nj = result[ti]
    ci = math.cos(ni["theta"])
    si = math.sin(ni["theta"])
    dx = nj["x"] - ni["x"]
    dy = nj["y"] - ni["y"]
    pred_dx = ci * dx + si * dy
    pred_dy = -si * dx + ci * dy
    res_dx = pred_dx - edge["dx"]
    res_dy = pred_dy - edge["dy"]
    return math.sqrt(res_dx ** 2 + res_dy ** 2)


def test_loop_closure_quality(result, pose_graph):
    """At least 4 of the 7 loop closure edges should be well-satisfied.

    True loop closures (5) should have small residuals; outliers (2) will not.
    """
    lc_edges = [e for e in pose_graph["edges"] if e["type"] == "loop_closure"]
    well_fitted = 0
    for edge in lc_edges:
        res = _compute_lc_residual(result, edge["from_id"], edge["to_id"], edge)
        if res < 2.0:
            well_fitted += 1
    assert well_fitted >= 4, (
        f"Only {well_fitted}/7 loop closures well-fitted (expected >=4). "
        f"The optimizer may not be correctly handling the pose graph constraints."
    )


def test_outlier_resistance_14_1(result):
    """Outlier edge 14->1 must not pull those nodes together.

    Node 14 is on the return leg at x~25, node 1 is on the forward leg at x~5.
    True distance ~20m. Outlier claims they overlap.
    """
    n14 = result[14]
    n1 = result[1]
    dist = math.sqrt((n14["x"] - n1["x"]) ** 2 + (n14["y"] - n1["y"]) ** 2)
    assert dist > 10.0, (
        f"Nodes 14 and 1 only {dist:.1f}m apart (should be ~20m). "
        f"Outlier loop closure not properly down-weighted."
    )


def test_outlier_resistance_16_8(result):
    """Outlier edge 16->8 must not pull those nodes together.

    Node 16 is on the return leg at x~15, node 8 is on the forward leg at x~40.
    True distance ~25m. Outlier claims they overlap.
    """
    n16 = result[16]
    n8 = result[8]
    dist = math.sqrt((n16["x"] - n8["x"]) ** 2 + (n16["y"] - n8["y"]) ** 2)
    assert dist > 15.0, (
        f"Nodes 16 and 8 only {dist:.1f}m apart (should be ~25m). "
        f"Outlier loop closure not properly down-weighted."
    )


def test_optimizer_modified_poses(result, pose_graph):
    """The optimizer must have actually modified the initial poses."""
    initial = {n["id"]: (n["x"], n["y"]) for n in pose_graph["nodes"]}
    changes = 0
    for node in result:
        dx = node["x"] - initial[node["id"]][0]
        dy = node["y"] - initial[node["id"]][1]
        if math.sqrt(dx * dx + dy * dy) > 0.01:
            changes += 1
    assert changes >= 5, (
        f"Only {changes} nodes moved >0.01m from initial. "
        f"The optimizer may not have run."
    )


def test_loop_closure_nodes_colocated(result):
    """Nodes connected by true loop closures should be approximately co-located.

    Pairs (19,0), (17,2), (15,4), (13,6), (11,8) represent the same physical
    positions visited in opposite directions. After optimization, at least 3
    pairs should be within 3m of each other.
    """
    pairs = [(19, 0), (17, 2), (15, 4), (13, 6), (11, 8)]
    close_count = 0
    for fi, ti in pairs:
        ni = result[fi]
        nj = result[ti]
        dist = math.sqrt((ni["x"] - nj["x"]) ** 2 + (ni["y"] - nj["y"]) ** 2)
        if dist < 3.0:
            close_count += 1
    assert close_count >= 3, (
        f"Only {close_count}/5 true loop-closure node pairs are within 3m. "
        f"The optimizer is not properly satisfying loop closure constraints."
    )
