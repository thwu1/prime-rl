
import json
import subprocess
import os
import re
import tempfile
import pytest


REGISTRY_PATH = "/app/registry.json"
MANIFESTS_DIR = "/app/manifests"


def run_resolver(manifest_name, extra_args=None, timeout=60):
    """Run the resolver CLI and return (returncode, stdout, stderr)."""
    cmd = ["python3", "/app/resolve.py"]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(os.path.join(MANIFESTS_DIR, manifest_name))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def load_registry():
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def parse_version(v):
    parts = v.strip().split(".")
    return tuple(int(p) for p in parts)


def version_satisfies(version_str, constraint):
    """Independent constraint checker for test verification."""
    v = parse_version(version_str)
    constraint = constraint.strip()

    if constraint.startswith("^"):
        base = parse_version(constraint[1:])
        if base[0] > 0:
            upper = (base[0] + 1, 0, 0)
        elif base[1] > 0:
            upper = (0, base[1] + 1, 0)
        else:
            upper = (0, 0, base[2] + 1)
        return base <= v < upper

    if constraint.startswith("~"):
        base = parse_version(constraint[1:])
        upper = (base[0], base[1] + 1, 0)
        return base <= v < upper

    # Range: >=X.Y.Z <A.B.C
    parts = re.findall(r"(>=|<=|>|<)\s*(\d+\.\d+\.\d+)", constraint)
    if not parts:
        # Exact match
        return v == parse_version(constraint)
    for op, ver in parts:
        target = parse_version(ver)
        if op == ">=" and not (v >= target):
            return False
        if op == "<" and not (v < target):
            return False
        if op == "<=" and not (v <= target):
            return False
        if op == ">" and not (v > target):
            return False
    return True


def verify_lockfile(lockfile, manifest_name):
    """Verify a lockfile satisfies all dependency constraints."""
    registry = load_registry()
    with open(os.path.join(MANIFESTS_DIR, manifest_name)) as f:
        manifest = json.load(f)
    packages = registry["packages"]

    # 1. All root deps present and in range
    for pkg, constraint in manifest["dependencies"].items():
        assert pkg in lockfile, f"Missing root dependency: {pkg}"
        assert version_satisfies(lockfile[pkg], constraint), (
            f"{pkg}={lockfile[pkg]} does not satisfy root constraint {constraint}"
        )

    # 2. All transitive deps present and in range
    for pkg, version in lockfile.items():
        assert pkg in packages, f"Package {pkg} not in registry"
        assert version in packages[pkg], f"{pkg}@{version} not in registry"
        deps = packages[pkg][version].get("dependencies", {})
        for dep_pkg, dep_constraint in deps.items():
            assert dep_pkg in lockfile, (
                f"{pkg}@{version} requires {dep_pkg} ({dep_constraint}) "
                f"but it is missing from lockfile"
            )
            assert version_satisfies(lockfile[dep_pkg], dep_constraint), (
                f"{dep_pkg}={lockfile[dep_pkg]} does not satisfy "
                f"{pkg}@{version}'s constraint {dep_constraint}"
            )

    # 3. No extraneous packages (all reachable from root)
    reachable = set()
    to_visit = list(manifest["dependencies"].keys())
    while to_visit:
        p = to_visit.pop()
        if p in reachable:
            continue
        reachable.add(p)
        v = lockfile[p]
        for dep in packages[p][v].get("dependencies", {}):
            if dep not in reachable:
                to_visit.append(dep)
    for pkg in lockfile:
        assert pkg in reachable, f"Package {pkg} in lockfile but not reachable from root"

    # 4. Only one version per package (implicit: lockfile is a dict)
    return True


# ============================================================
# Test: Simple resolution (logging + config)
# ============================================================

class TestSimpleResolution:
    def test_resolves_successfully(self):
        code, stdout, stderr = run_resolver("simple.json")
        assert code == 0, f"Resolver failed: {stderr}"
        lockfile = json.loads(stdout)
        verify_lockfile(lockfile, "simple.json")

    def test_correct_package_set(self):
        code, stdout, _ = run_resolver("simple.json")
        assert code == 0
        lockfile = json.loads(stdout)
        assert set(lockfile.keys()) == {"logging", "config", "json"}

    def test_latest_logging(self):
        """logging ^1.0.0 should resolve to 1.1.0 (latest), not 1.0.0."""
        code, stdout, _ = run_resolver("simple.json")
        assert code == 0
        lockfile = json.loads(stdout)
        assert lockfile["logging"] == "1.1.0", (
            f"Expected logging=1.1.0 (latest in ^1.0.0), got {lockfile['logging']}"
        )

    def test_latest_json(self):
        """json ^1.0.0 should resolve to 1.2.0 (latest), not 1.0.0."""
        code, stdout, _ = run_resolver("simple.json")
        assert code == 0
        lockfile = json.loads(stdout)
        assert lockfile["json"] == "1.2.0", (
            f"Expected json=1.2.0 (latest in ^1.0.0), got {lockfile['json']}"
        )


# ============================================================
# Test: Diamond dependency (router + database share json/logging)
# ============================================================

class TestDiamondResolution:
    def test_resolves_successfully(self):
        code, stdout, stderr = run_resolver("diamond.json")
        assert code == 0, f"Resolver failed: {stderr}"
        lockfile = json.loads(stdout)
        verify_lockfile(lockfile, "diamond.json")

    def test_expected_packages_present(self):
        code, stdout, _ = run_resolver("diamond.json")
        assert code == 0
        lockfile = json.loads(stdout)
        required = {"router", "http", "database", "json", "logging"}
        assert required.issubset(set(lockfile.keys())), (
            f"Missing packages: {required - set(lockfile.keys())}"
        )

    def test_shared_json_version(self):
        """Both http and database need json — must be a single version."""
        code, stdout, _ = run_resolver("diamond.json")
        assert code == 0
        lockfile = json.loads(stdout)
        assert "json" in lockfile
        # json must be in ^2.0.0 (intersection of http and database constraints)
        v = parse_version(lockfile["json"])
        assert (2, 0, 0) <= v < (3, 0, 0), (
            f"json should be 2.x (shared constraint), got {lockfile['json']}"
        )


# ============================================================
# Test: Deep transitive chain (session + mailer + scheduler)
# ============================================================

class TestDeepResolution:
    def test_resolves_successfully(self):
        code, stdout, stderr = run_resolver("deep.json")
        assert code == 0, f"Resolver failed: {stderr}"
        lockfile = json.loads(stdout)
        verify_lockfile(lockfile, "deep.json")

    def test_many_transitive_deps(self):
        code, stdout, _ = run_resolver("deep.json")
        assert code == 0
        lockfile = json.loads(stdout)
        assert len(lockfile) >= 10, (
            f"Expected >= 10 packages in deep resolution, got {len(lockfile)}"
        )

    def test_solves_within_timeout(self):
        """The resolver must solve deep.json within 30 seconds.
        With 33 boolean variables, brute-force enumeration (2^33 ~ 8.6B
        iterations) is intractable — an efficient SAT backend is required."""
        try:
            code, stdout, stderr = run_resolver("deep.json", timeout=30)
        except subprocess.TimeoutExpired:
            pytest.fail(
                "Resolver timed out on deep.json (30s limit). "
                "Brute-force enumeration cannot handle 33 variables — "
                "use MiniSat as the SAT backend."
            )
        assert code == 0, f"Solver failed: {stderr}"


# ============================================================
# Test: Conflict detection (orm ^2 + cache ^1 = unsatisfiable)
# ============================================================

class TestConflictDetection:
    def test_reports_conflict(self):
        code, stdout, stderr = run_resolver("conflict.json")
        assert code == 1, (
            "Resolver should exit 1 for unsatisfiable dependencies, "
            f"got exit code {code}"
        )

    def test_error_on_stderr(self):
        code, _, stderr = run_resolver("conflict.json")
        assert code == 1
        assert len(stderr.strip()) > 0, (
            "Should output conflict message to stderr"
        )

    def test_no_lockfile_on_stdout(self):
        code, stdout, _ = run_resolver("conflict.json")
        assert code == 1
        # stdout should be empty or not valid JSON lockfile
        stdout = stdout.strip()
        if stdout:
            try:
                obj = json.loads(stdout)
                assert not isinstance(obj, dict) or len(obj) == 0, (
                    "Should not output a lockfile for unsatisfiable deps"
                )
            except json.JSONDecodeError:
                pass  # non-JSON output is fine for error case


# ============================================================
# Test: Conflict diagnostic quality
# ============================================================

class TestConflictDiagnostic:
    """When resolution fails, the diagnostic must provide actionable analysis
    of the conflicting constraints — not just a generic error message."""

    def test_identifies_conflicting_shared_dependency(self):
        """Must name at least one package whose version constraints are
        irreconcilable (json and/or logging for the conflict manifest)."""
        code, _, stderr = run_resolver("conflict.json")
        assert code == 1
        # The conflict: orm@2.0.0 -> database@3.0.0 -> {json ^2.0.0, logging ^2.0.0}
        #               cache@1.0.0 -> {json ^1.0.0, logging ^1.0.0}
        # json ^2.0.0 ∩ json ^1.0.0 = ∅,  logging ^2.0.0 ∩ logging ^1.0.0 = ∅
        found = any(pkg in stderr for pkg in ["json", "logging"])
        assert found, (
            f"Diagnostic must name the package(s) with conflicting constraints. "
            f"stderr:\n{stderr}"
        )

    def test_references_conflicting_dependents(self):
        """Must trace which packages impose the incompatible constraints."""
        code, _, stderr = run_resolver("conflict.json")
        assert code == 1
        # The conflict chain involves orm, cache, and/or database
        sources_found = sum(1 for p in ["orm", "cache", "database"] if p in stderr)
        assert sources_found >= 2, (
            f"Diagnostic must reference >= 2 packages in the conflict chain "
            f"(orm, cache, database). stderr:\n{stderr}"
        )

    def test_includes_version_constraint_details(self):
        """Must show actual version numbers, not just package names."""
        code, _, stderr = run_resolver("conflict.json")
        assert code == 1
        version_re = re.compile(r'\d+\.\d+\.\d+')
        versions = version_re.findall(stderr)
        assert len(versions) >= 2, (
            f"Diagnostic must include version constraint details. stderr:\n{stderr}"
        )

    def test_provides_multiline_detail(self):
        """Diagnostic must be detailed enough to be actionable (>= 3 lines)."""
        code, _, stderr = run_resolver("conflict.json")
        assert code == 1
        lines = [l for l in stderr.strip().split('\n') if l.strip()]
        assert len(lines) >= 3, (
            f"Diagnostic must be multi-line with sufficient detail. stderr:\n{stderr}"
        )


# ============================================================
# Test: Constrained resolution with tilde (~) constraint
# ============================================================

class TestConstrainedResolution:
    def test_resolves_successfully(self):
        code, stdout, stderr = run_resolver("constrained.json")
        assert code == 0, f"Resolver failed: {stderr}"
        lockfile = json.loads(stdout)
        verify_lockfile(lockfile, "constrained.json")

    def test_tilde_forces_exact_version(self):
        """~2.0.0 means >=2.0.0 <2.1.0, so logging must be exactly 2.0.0."""
        code, stdout, _ = run_resolver("constrained.json")
        assert code == 0
        lockfile = json.loads(stdout)
        assert lockfile["logging"] == "2.0.0", (
            f"~2.0.0 should resolve to 2.0.0, got {lockfile['logging']}"
        )

    def test_caret_on_root_deps(self):
        """Caret constraints in root deps should be respected."""
        code, stdout, _ = run_resolver("constrained.json")
        assert code == 0
        lockfile = json.loads(stdout)
        # router ^2.0.0 => 2.x
        v = parse_version(lockfile["router"])
        assert (2, 0, 0) <= v < (3, 0, 0)
        # orm ^1.0.0 => 1.x
        v = parse_version(lockfile["orm"])
        assert (1, 0, 0) <= v < (2, 0, 0)
        # auth ^2.0.0 => 2.x
        v = parse_version(lockfile["auth"])
        assert (2, 0, 0) <= v < (3, 0, 0)


# ============================================================
# Test: DIMACS CNF export format
# ============================================================

class TestDIMACSExport:
    def test_format_header(self):
        code, stdout, _ = run_resolver("simple.json", ["--dimacs"])
        assert code == 0
        lines = stdout.strip().split("\n")
        p_lines = [l for l in lines if l.startswith("p cnf")]
        assert len(p_lines) == 1, "Must have exactly one 'p cnf' header line"
        parts = p_lines[0].split()
        assert len(parts) == 4, f"Header format: 'p cnf <vars> <clauses>', got: {p_lines[0]}"
        num_vars = int(parts[2])
        num_clauses = int(parts[3])
        assert num_vars > 0, "Must have at least one variable"
        assert num_clauses > 0, "Must have at least one clause"

    def test_clause_count_matches(self):
        code, stdout, _ = run_resolver("simple.json", ["--dimacs"])
        assert code == 0
        lines = stdout.strip().split("\n")
        header = [l for l in lines if l.startswith("p cnf")][0]
        num_clauses = int(header.split()[3])
        clause_lines = [
            l for l in lines
            if l.strip() and not l.startswith("c") and not l.startswith("p")
        ]
        assert len(clause_lines) == num_clauses, (
            f"Header says {num_clauses} clauses, found {len(clause_lines)}"
        )

    def test_clause_syntax(self):
        code, stdout, _ = run_resolver("simple.json", ["--dimacs"])
        assert code == 0
        lines = stdout.strip().split("\n")
        for line in lines:
            if line.startswith("c") or line.startswith("p"):
                continue
            line = line.strip()
            if not line:
                continue
            assert line.endswith("0"), f"Clause must end with 0: {line}"
            literals = line.split()
            for lit in literals[:-1]:
                n = int(lit)
                assert n != 0, "Literal 0 only allowed as terminator"

    def test_variable_comments(self):
        code, stdout, _ = run_resolver("simple.json", ["--dimacs"])
        assert code == 0
        lines = stdout.strip().split("\n")
        var_comments = [l for l in lines if l.startswith("c var")]
        assert len(var_comments) > 0, "Should have variable mapping comments"
        for vc in var_comments:
            parts = vc.split()
            assert len(parts) >= 4, f"Bad var comment format: {vc}"
            assert parts[1] == "var"
            int(parts[2])  # must be parseable int
            assert "@" in parts[3], f"Variable name should be pkg@ver: {parts[3]}"

    def test_dimacs_export_for_unsat(self):
        """DIMACS export should succeed even for unsatisfiable manifests."""
        code, stdout, _ = run_resolver("conflict.json", ["--dimacs"])
        assert code == 0, "DIMACS export should exit 0 even for unsat formulas"
        assert "p cnf" in stdout

    def test_mutual_exclusion_clauses_present(self):
        """DIMACS output must include mutual exclusion clauses (binary
        negative clauses) preventing multiple versions of the same package."""
        code, stdout, _ = run_resolver("simple.json", ["--dimacs"])
        assert code == 0
        lines = stdout.strip().split("\n")
        # Collect variable-to-package mapping
        pkg_of_var = {}
        for line in lines:
            if line.startswith("c var"):
                parts = line.split()
                vid = int(parts[2])
                pkg = parts[3].split("@")[0]
                pkg_of_var[vid] = pkg
        # Find binary negative clauses (mutual exclusion)
        mutex_found = False
        for line in lines:
            if line.startswith("c") or line.startswith("p") or not line.strip():
                continue
            lits = [int(x) for x in line.strip().split()]
            if len(lits) == 3 and lits[-1] == 0:  # binary clause + terminator
                l1, l2 = lits[0], lits[1]
                if l1 < 0 and l2 < 0:
                    v1, v2 = abs(l1), abs(l2)
                    if v1 in pkg_of_var and v2 in pkg_of_var:
                        if pkg_of_var[v1] == pkg_of_var[v2]:
                            mutex_found = True
                            break
        assert mutex_found, (
            "DIMACS output must contain mutual exclusion clauses "
            "(pairwise negative literals for versions of the same package)"
        )


# ============================================================
# Test: MiniSat cross-validation
# ============================================================

class TestMiniSatCrossValidation:
    def test_minisat_agrees_sat(self):
        """MiniSat should agree that the diamond formula is satisfiable."""
        code, stdout, _ = run_resolver("diamond.json", ["--dimacs"])
        assert code == 0
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cnf", delete=False
        ) as f:
            f.write(stdout)
            cnf_path = f.name
        try:
            ms = subprocess.run(
                ["minisat", cnf_path, "/tmp/ms_sat_out.txt"],
                capture_output=True, text=True, timeout=30,
            )
            assert ms.returncode == 10, (
                f"MiniSat should return 10 (SAT), got {ms.returncode}"
            )
        finally:
            os.unlink(cnf_path)

    def test_minisat_agrees_unsat(self):
        """MiniSat should agree that the conflict formula is unsatisfiable."""
        code, stdout, _ = run_resolver("conflict.json", ["--dimacs"])
        assert code == 0
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cnf", delete=False
        ) as f:
            f.write(stdout)
            cnf_path = f.name
        try:
            ms = subprocess.run(
                ["minisat", cnf_path, "/tmp/ms_unsat_out.txt"],
                capture_output=True, text=True, timeout=30,
            )
            assert ms.returncode == 20, (
                f"MiniSat should return 20 (UNSAT), got {ms.returncode}"
            )
        finally:
            os.unlink(cnf_path)

    def test_minisat_agrees_deep(self):
        """MiniSat should agree the deep formula is satisfiable."""
        code, stdout, _ = run_resolver("deep.json", ["--dimacs"])
        assert code == 0
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cnf", delete=False
        ) as f:
            f.write(stdout)
            cnf_path = f.name
        try:
            ms = subprocess.run(
                ["minisat", cnf_path, "/tmp/ms_deep_out.txt"],
                capture_output=True, text=True, timeout=30,
            )
            assert ms.returncode == 10, (
                f"MiniSat should return 10 (SAT), got {ms.returncode}"
            )
        finally:
            os.unlink(cnf_path)


# ============================================================
# Test: Semver constraint parsing correctness
# ============================================================

class TestSemverConstraints:
    def test_caret_does_not_cross_major(self):
        """^1.0.0 should not resolve logging to 2.x."""
        code, stdout, _ = run_resolver("simple.json")
        assert code == 0
        lockfile = json.loads(stdout)
        v = parse_version(lockfile["logging"])
        assert v[0] == 1, f"logging should be 1.x under ^1.0.0, got {lockfile['logging']}"

    def test_range_constraint_bounds(self):
        """>=2.0.0 <4.0.0 should select within that range."""
        code, stdout, _ = run_resolver("diamond.json")
        assert code == 0
        lockfile = json.loads(stdout)
        v = parse_version(lockfile["database"])
        assert (2, 0, 0) <= v < (4, 0, 0), (
            f"database should be in [2.0.0, 4.0.0), got {lockfile['database']}"
        )

    def test_tilde_constraint_range(self):
        """~2.0.0 should match [2.0.0, 2.1.0)."""
        code, stdout, _ = run_resolver("constrained.json")
        assert code == 0
        lockfile = json.loads(stdout)
        v = parse_version(lockfile["logging"])
        assert (2, 0, 0) <= v < (2, 1, 0), (
            f"logging should be in [2.0.0, 2.1.0) under ~2.0.0, got {lockfile['logging']}"
        )
