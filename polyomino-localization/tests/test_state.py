
"""Tests for polyomino localization pipeline output."""
import os
import random
import sqlite3
import pytest

_SEEDS = [314159, 271828, 161803, 141421, 173205, 223606, 244949, 264575]
_GS = 20
_NP = 5
_CMIN = 3
_CMAX = 7
_N = 8
_THRESH = 0.85
_RESULT_DB = "/app/results.db"


def _regen(seed):
    """Regenerate ground truth grid from seed."""
    g = random.Random(seed)
    occ = set()
    polys = []
    offs = []
    for _ in range(_NP):
        nc = g.randint(_CMIN, _CMAX)
        cl = [(0, 0)]
        for _ in range(nc - 1):
            cs = set(cl)
            nb = set()
            for r, c in cl:
                for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    p = (r + dr, c + dc)
                    if p not in cs:
                        nb.add(p)
            cands = sorted(nb)
            cl.append(cands[g.randint(0, len(cands) - 1)])
        mr = min(r for r, c in cl)
        mc = min(c for r, c in cl)
        cl = sorted((r - mr, c - mc) for r, c in cl)
        xr = max(r for r, c in cl)
        xc = max(c for r, c in cl)
        vp = []
        for dr in range(_GS - xr):
            for dc in range(_GS - xc):
                pl = frozenset((r + dr, c + dc) for r, c in cl)
                if not pl & occ:
                    vp.append((dr, dc))
        if not vp:
            continue
        o = vp[g.randint(0, len(vp) - 1)]
        polys.append(cl)
        offs.append(o)
        for r, c in cl:
            occ.add((r + o[0], c + o[1]))
    grid = [[0] * _GS for _ in range(_GS)]
    for cl, (dr, dc) in zip(polys, offs):
        for r, c in cl:
            grid[r + dr][c + dc] = 1
    return grid


def _f1(pred, truth):
    tp = fp = fn = 0
    for r in range(_GS):
        for c in range(_GS):
            p, t = pred[r][c], truth[r][c]
            if p and t:
                tp += 1
            elif p and not t:
                fp += 1
            elif not p and t:
                fn += 1
    if tp == 0:
        return 0.0
    pr = tp / (tp + fp)
    rc = tp / (tp + fn)
    return 2 * pr * rc / (pr + rc)


def _load_result(inst_id):
    """Load result grid from SQLite database."""
    conn = sqlite3.connect(_RESULT_DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT row, col, value FROM solutions WHERE instance_id = ?",
        (inst_id,)
    )
    rows = cur.fetchall()
    conn.close()
    grid = [[0] * _GS for _ in range(_GS)]
    for r, c, v in rows:
        grid[r][c] = v
    return grid, len(rows)


class TestDatabaseExists:
    def test_results_db_exists(self):
        assert os.path.isfile(_RESULT_DB), (
            f"Results database {_RESULT_DB} not found."
        )


class TestSchema:
    def test_solutions_table_exists(self):
        if not os.path.isfile(_RESULT_DB):
            pytest.skip("Results database missing")
        conn = sqlite3.connect(_RESULT_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='solutions'"
        )
        assert cur.fetchone() is not None, "Table 'solutions' not found"
        conn.close()

    def test_solutions_columns(self):
        if not os.path.isfile(_RESULT_DB):
            pytest.skip("Results database missing")
        conn = sqlite3.connect(_RESULT_DB)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(solutions)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        expected = {"instance_id", "row", "col", "value"}
        assert expected.issubset(cols), (
            f"Missing columns: {expected - cols}"
        )

    @pytest.mark.parametrize("i", range(_N))
    def test_instance_cell_count(self, i):
        if not os.path.isfile(_RESULT_DB):
            pytest.skip("Results database missing")
        _, count = _load_result(i)
        assert count == _GS * _GS, (
            f"Instance {i}: expected {_GS * _GS} cells, got {count}"
        )

    @pytest.mark.parametrize("i", range(_N))
    def test_values_binary(self, i):
        if not os.path.isfile(_RESULT_DB):
            pytest.skip("Results database missing")
        conn = sqlite3.connect(_RESULT_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM solutions "
            "WHERE instance_id = ? AND value NOT IN (0, 1)",
            (i,)
        )
        bad = cur.fetchone()[0]
        conn.close()
        assert bad == 0, (
            f"Instance {i}: {bad} cells have non-binary values"
        )


class TestF1Score:
    def test_average_f1(self):
        if not os.path.isfile(_RESULT_DB):
            pytest.fail("Results database missing")
        scores = []
        for i in range(_N):
            truth = _regen(_SEEDS[i])
            pred, cnt = _load_result(i)
            if cnt == 0:
                scores.append(0.0)
                continue
            scores.append(_f1(pred, truth))
        avg = sum(scores) / len(scores)
        detail = ", ".join(f"{s:.4f}" for s in scores)
        assert avg >= _THRESH, (
            f"Average F1 = {avg:.4f} < {_THRESH}. "
            f"Per-instance: [{detail}]"
        )

    @pytest.mark.parametrize("i", range(_N))
    def test_nonzero_f1(self, i):
        if not os.path.isfile(_RESULT_DB):
            pytest.skip("Results database missing")
        truth = _regen(_SEEDS[i])
        pred, _ = _load_result(i)
        f1 = _f1(pred, truth)
        assert f1 > 0.0, f"Instance {i}: F1 = 0.0"
