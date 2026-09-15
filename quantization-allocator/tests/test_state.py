
"""
Tests for the quantization DAG optimizer.
Verifies strategy.json against multi-format data sources:
  SQLite (model.db), Parquet (measurements/), TOML (constraints.toml)
"""

import json
import os
import sqlite3
import tomllib
import pyarrow.parquet as pq
import pytest


def load_all():
    """Load data from all three sources."""
    conn = sqlite3.connect("/app/model.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT value FROM architecture WHERE key='weight_budget'")
    weight_budget = int(cur.fetchone()["value"])

    cur.execute(
        "SELECT id, layer_idx, module_type, numel "
        "FROM modules ORDER BY id")
    modules = [dict(r) for r in cur.fetchall()]

    cur.execute(
        "SELECT src_module_id, dst_module_id, propagation_coeff "
        "FROM dag_edges")
    edges = cur.fetchall()
    conn.close()

    predecessors = {m["id"]: [] for m in modules}
    successors = {m["id"]: [] for m in modules}
    dag_coeffs = {}
    for e in edges:
        s = e["src_module_id"]
        d = e["dst_module_id"]
        c = e["propagation_coeff"]
        predecessors[d].append(s)
        successors[s].append(d)
        dag_coeffs[(s, d)] = c

    measurements = {}
    for grp in ("attention", "mlp", "router", "expert"):
        tbl = pq.read_table("/app/measurements/%s.parquet" % grp)
        df = tbl.to_pydict()
        for i in range(len(df["module_id"])):
            mid = df["module_id"][i]
            if mid not in measurements:
                measurements[mid] = []
            measurements[mid].append({
                "option_idx": df["option_idx"][i],
                "total_bits": df["total_bits"][i],
                "error": df["error"][i],
                "bpw": df["bpw"][i],
            })
    for mid in measurements:
        measurements[mid].sort(key=lambda x: x["option_idx"])

    with open("/app/constraints.toml", "rb") as f:
        constraints = tomllib.load(f)
    layer_groups = [
        lg for lg in constraints.get("layer_groups", [])
        if lg.get("min_bpw", 0) > 0]
    pinned = {}
    for pm in constraints.get("pinned_modules", []):
        pinned[pm["module_id"]] = pm["required_min_bpw"]

    return (modules, measurements, weight_budget,
            predecessors, successors, dag_coeffs, layer_groups, pinned)


def get_eligible(modules, measurements, pinned, layer_groups):
    eligible = {}
    for mod in modules:
        mid = mod["id"]
        li = mod["layer_idx"]
        min_bpw = 0.0
        if mid in pinned:
            min_bpw = max(min_bpw, pinned[mid])
        for lg in layer_groups:
            if lg["start_layer"] <= li <= lg["end_layer"]:
                min_bpw = max(min_bpw, lg["min_bpw"])
        opts = []
        for m in measurements[mid]:
            if m["bpw"] >= min_bpw - 1e-9:
                opts.append((m["option_idx"], m["total_bits"], m["error"]))
        eligible[mid] = opts
    return eligible


def compute_eff_errors(module_ids, own_errors, predecessors, dag_coeffs):
    """Compute effective errors with recursive DAG propagation."""
    eff = {}
    for mid in module_ids:
        upstream = sum(
            dag_coeffs.get((p, mid), 0) * eff[p]
            for p in predecessors[mid] if p in eff)
        eff[mid] = own_errors[mid] + upstream
    return eff


def solve_reference(modules, eligible, weight_budget,
                    predecessors, dag_coeffs):
    """Compute reference optimal solution."""
    module_ids = [m["id"] for m in modules]
    max_raw = max(
        err for mid in module_ids for _, _, err in eligible[mid])
    lo, hi = 0.0, max_raw * 1.5
    best_assign = None

    for _ in range(200):
        T = (lo + hi) / 2.0
        assignment = {}
        eff_so_far = {}
        total = 0
        feasible = True
        for mid in module_ids:
            upstream = sum(
                dag_coeffs.get((p, mid), 0) * eff_so_far[p]
                for p in predecessors[mid] if p in eff_so_far)
            max_own = T - upstream
            best_opt = None
            best_bits = float("inf")
            for oidx, bits, err in eligible[mid]:
                if err <= max_own + 1e-15 and bits < best_bits:
                    best_opt = (oidx, bits, err)
                    best_bits = bits
            if best_opt is None:
                feasible = False
                break
            assignment[mid] = best_opt
            eff_so_far[mid] = best_opt[2] + upstream
            total += best_bits
        if feasible and total <= weight_budget:
            best_assign = dict(assignment)
            hi = T
        else:
            lo = T

    if best_assign is None:
        return None

    # Greedy post-processing
    total = sum(best_assign[mid][1] for mid in module_ids)
    changed = True
    while changed:
        changed = False
        own_map = {mid: best_assign[mid][2] for mid in module_ids}
        eff = compute_eff_errors(module_ids, own_map,
                                 predecessors, dag_coeffs)
        best_upgrade = None
        best_priority = None
        for mid in module_ids:
            oidx0, bits0, err0 = best_assign[mid]
            eff0 = eff[mid]
            for oidx, bits, err in eligible[mid]:
                if oidx == oidx0:
                    continue
                delta = bits - bits0
                if delta <= 0 or total + delta > weight_budget:
                    continue
                if err >= err0 - 1e-15:
                    continue
                priority = (eff0, err0 - err, -mid)
                if best_priority is None or priority > best_priority:
                    best_priority = priority
                    best_upgrade = (mid, oidx, bits, err, delta)
        if best_upgrade:
            mid, oidx, bits, err, delta = best_upgrade
            best_assign[mid] = (oidx, bits, err)
            total += delta
            changed = True

    own_map = {mid: best_assign[mid][2] for mid in module_ids}
    eff = compute_eff_errors(module_ids, own_map,
                             predecessors, dag_coeffs)
    return best_assign, max(eff.values())


def load_strategy():
    with open("/app/strategy.json") as f:
        return json.load(f)


class TestFileExists:

    def test_file_exists(self):
        assert os.path.exists("/app/strategy.json"), \
            "strategy.json not found at /app/strategy.json"

    def test_valid_json(self):
        with open("/app/strategy.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)


class TestStructure:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.strategy = load_strategy()
        data = load_all()
        self.modules = data[0]

    def test_has_assignments(self):
        assert "assignments" in self.strategy

    def test_assignment_count(self):
        expected = len(self.modules)
        actual = len(self.strategy["assignments"])
        assert actual == expected, \
            "Expected %d assignments, got %d" % (expected, actual)

    def test_assignment_fields(self):
        for i, a in enumerate(self.strategy["assignments"]):
            assert "module_id" in a, \
                "Assignment %d missing module_id" % i
            assert "option_idx" in a, \
                "Assignment %d missing option_idx" % i

    def test_assignment_ordering(self):
        for i, a in enumerate(self.strategy["assignments"]):
            expected_id = self.modules[i]["id"]
            assert a["module_id"] == expected_id, \
                "Assignment %d: expected module_id %d, got %d" % (
                    i, expected_id, a["module_id"])

    def test_has_required_fields(self):
        for field in ("total_bits", "weight_budget",
                      "max_effective_error", "max_raw_error"):
            assert field in self.strategy, \
                "Missing field: %s" % field


class TestConstraints:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.strategy = load_strategy()
        (self.modules, self.meas, self.budget,
         self.preds, self.succs, self.coeffs,
         self.lg, self.pinned) = load_all()

    def _opt(self, mid, oidx):
        for m in self.meas[mid]:
            if m["option_idx"] == oidx:
                return m
        return None

    def test_valid_options(self):
        for a in self.strategy["assignments"]:
            mid, oidx = a["module_id"], a["option_idx"]
            opt = self._opt(mid, oidx)
            assert opt is not None, \
                "Module %d: invalid option_idx %d" % (mid, oidx)

    def test_budget(self):
        total = sum(
            self._opt(a["module_id"], a["option_idx"])["total_bits"]
            for a in self.strategy["assignments"])
        assert total <= self.budget, \
            "Total bits %d exceeds budget %d" % (total, self.budget)

    def test_pinned_constraints(self):
        for a in self.strategy["assignments"]:
            mid = a["module_id"]
            if mid in self.pinned:
                opt = self._opt(mid, a["option_idx"])
                assert opt["bpw"] >= self.pinned[mid] - 1e-9, \
                    "Pinned module %d: bpw %.4f < required %.1f" % (
                        mid, opt["bpw"], self.pinned[mid])

    def test_layer_group_constraints(self):
        mod_map = {m["id"]: m for m in self.modules}
        for a in self.strategy["assignments"]:
            mid = a["module_id"]
            li = mod_map[mid]["layer_idx"]
            opt = self._opt(mid, a["option_idx"])
            for lg in self.lg:
                if lg["start_layer"] <= li <= lg["end_layer"]:
                    assert opt["bpw"] >= lg["min_bpw"] - 1e-9, (
                        "Module %d (layer %d, group %s): "
                        "bpw %.4f < required %.1f" % (
                            mid, li, lg["group_name"],
                            opt["bpw"], lg["min_bpw"]))

    def test_reported_total_bits(self):
        computed = sum(
            self._opt(a["module_id"], a["option_idx"])["total_bits"]
            for a in self.strategy["assignments"])
        reported = self.strategy["total_bits"]
        assert abs(computed - reported) < 1000, \
            "Reported total_bits %d != computed %d" % (
                reported, computed)

    def test_reported_max_raw_error(self):
        computed = max(
            self._opt(a["module_id"], a["option_idx"])["error"]
            for a in self.strategy["assignments"])
        reported = self.strategy["max_raw_error"]
        assert abs(computed - reported) < 1e-8, \
            "Reported max_raw_error %.10f != computed %.10f" % (
                reported, computed)


class TestEffectiveError:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.strategy = load_strategy()
        (self.modules, self.meas, self.budget,
         self.preds, self.succs, self.coeffs,
         self.lg, self.pinned) = load_all()
        self.module_ids = [m["id"] for m in self.modules]

    def _opt(self, mid, oidx):
        for m in self.meas[mid]:
            if m["option_idx"] == oidx:
                return m
        return None

    def test_effective_error_computation(self):
        """Verify max_effective_error uses recursive DAG propagation."""
        own_errors = {}
        for a in self.strategy["assignments"]:
            own_errors[a["module_id"]] = \
                self._opt(a["module_id"], a["option_idx"])["error"]

        eff = compute_eff_errors(
            self.module_ids, own_errors,
            self.preds, self.coeffs)
        computed_max = max(eff.values())
        reported = self.strategy["max_effective_error"]

        assert abs(computed_max - reported) < 1e-8, \
            "Reported max_effective_error %.10f != computed %.10f" % (
                reported, computed_max)

    def test_effective_exceeds_raw(self):
        """Effective error >= raw error for modules with predecessors."""
        own_errors = {}
        for a in self.strategy["assignments"]:
            own_errors[a["module_id"]] = \
                self._opt(a["module_id"], a["option_idx"])["error"]

        eff = compute_eff_errors(
            self.module_ids, own_errors,
            self.preds, self.coeffs)

        for mid in self.module_ids:
            if self.preds[mid]:
                assert eff[mid] >= own_errors[mid] - 1e-15, \
                    "Module %d: effective %.10f < raw %.10f" % (
                        mid, eff[mid], own_errors[mid])


class TestOptimality:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.strategy = load_strategy()
        (self.modules, self.meas, self.budget,
         self.preds, self.succs, self.coeffs,
         self.lg, self.pinned) = load_all()
        self.eligible = get_eligible(
            self.modules, self.meas, self.pinned, self.lg)
        self.module_ids = [m["id"] for m in self.modules]

    def _opt(self, mid, oidx):
        for m in self.meas[mid]:
            if m["option_idx"] == oidx:
                return m
        return None

    def test_near_optimal(self):
        """Agent's max effective error within 15% of reference."""
        own_errors = {}
        for a in self.strategy["assignments"]:
            own_errors[a["module_id"]] = \
                self._opt(a["module_id"], a["option_idx"])["error"]
        eff = compute_eff_errors(
            self.module_ids, own_errors,
            self.preds, self.coeffs)
        agent_max = max(eff.values())

        ref = solve_reference(
            self.modules, self.eligible, self.budget,
            self.preds, self.coeffs)
        assert ref is not None, "No feasible reference solution"
        _, ref_max = ref

        limit = ref_max * 1.15 + 1e-12
        assert agent_max <= limit, (
            "Agent max_eff %.10f exceeds reference %.10f "
            "by more than 15%% (limit: %.10f)" % (
                agent_max, ref_max, limit))

    def test_budget_utilization(self):
        """No single-module upgrade should reduce raw error
        within remaining budget."""
        total = sum(
            self._opt(a["module_id"], a["option_idx"])["total_bits"]
            for a in self.strategy["assignments"])
        remaining = self.budget - total

        assign_map = {}
        for a in self.strategy["assignments"]:
            assign_map[a["module_id"]] = a["option_idx"]

        for mid in self.module_ids:
            curr_oidx = assign_map[mid]
            curr_opt = self._opt(mid, curr_oidx)
            curr_err = curr_opt["error"]
            curr_bits = curr_opt["total_bits"]

            for oidx, bits, err in self.eligible[mid]:
                if oidx == curr_oidx:
                    continue
                delta = bits - curr_bits
                if (0 < delta <= remaining
                        and err < curr_err - 1e-15):
                    pytest.fail(
                        "Module %d: could upgrade from option %d "
                        "(err=%.10f) to option %d (err=%.10f) "
                        "for %d extra bits (%d remaining)" % (
                            mid, curr_oidx, curr_err,
                            oidx, err, delta, remaining))
