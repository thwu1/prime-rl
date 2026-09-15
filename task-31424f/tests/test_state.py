
import json
import subprocess
import sys
import os
import pytest

sys.path.insert(0, '/app')


# ---------------------------------------------------------------------------
# Spec conformance: Pessimistic constraint expansion
# ---------------------------------------------------------------------------

class TestPessimisticConstraintSpec:
    """Verify ~> operator conforms to spec/puppet_versioning.md."""

    def test_two_part_bumps_major(self):
        from resolver.constraints import parse_constraint, satisfies_all
        # ~> 7.0 means >= 7.0.0 < 8.0.0 (major bump)
        constraints = parse_constraint('~> 7.0')
        assert satisfies_all('7.0.0', constraints)
        assert satisfies_all('7.4.0', constraints)
        assert satisfies_all('7.99.0', constraints)
        assert not satisfies_all('8.0.0', constraints)
        assert not satisfies_all('6.9.0', constraints)

    def test_two_part_nonzero_minor(self):
        from resolver.constraints import parse_constraint, satisfies_all
        # ~> 8.1 means >= 8.1.0 < 9.0.0 (major bump, NOT minor bump)
        constraints = parse_constraint('~> 8.1')
        assert satisfies_all('8.1.0', constraints)
        assert satisfies_all('8.2.0', constraints)
        assert satisfies_all('8.99.0', constraints)
        assert not satisfies_all('9.0.0', constraints)
        assert not satisfies_all('8.0.0', constraints)

    def test_three_part_bumps_minor(self):
        from resolver.constraints import parse_constraint, satisfies_all
        # ~> 8.6.0 means >= 8.6.0 < 8.7.0 (minor bump)
        constraints = parse_constraint('~> 8.6.0')
        assert satisfies_all('8.6.0', constraints)
        assert satisfies_all('8.6.5', constraints)
        assert not satisfies_all('8.7.0', constraints)
        assert not satisfies_all('8.5.0', constraints)


# ---------------------------------------------------------------------------
# Spec conformance: Case-insensitive module name resolution
# ---------------------------------------------------------------------------

class TestCaseInsensitiveResolution:
    """Verify case-insensitive module matching per spec."""

    def test_resolve_cased_dependency(self):
        from resolver.solver import Solver
        solver = Solver('/app/forge_db/modules.json')
        # prometheus depends on "Puppetlabs/Stdlib" (capitalized in forge metadata)
        result = solver.resolve([('voxpupuli/prometheus', [])])
        assert result['status'] == 'ok', f"Resolution failed: {result}"
        modules = {m['name']: m['version'] for m in result['modules']}
        assert 'puppetlabs/stdlib' in modules
        assert modules['voxpupuli/prometheus'] == '14.0.0'


# ---------------------------------------------------------------------------
# Spec conformance: Backtracking with visited-set restoration
# ---------------------------------------------------------------------------

class TestBacktracking:
    """Verify visited set is restored during backtracking per spec."""

    def test_cross_context_retry(self):
        from resolver.solver import Solver
        solver = Solver('/app/forge_db/modules.json')
        result = solver.resolve([
            ('voxpupuli/victorialogs', []),
            ('voxpupuli/augeasproviders', []),
        ])
        assert result['status'] == 'ok', f"Resolution failed (should be solvable): {result}"
        modules = {m['name']: m['version'] for m in result['modules']}
        assert modules['voxpupuli/victorialogs'] == '1.0.0'
        assert modules['voxpupuli/augeasproviders'] == '1.0.0'
        assert modules['voxpupuli/systemd'] == '1.0.0'


# ---------------------------------------------------------------------------
# Spec conformance: Git-sourced entry filtering
# ---------------------------------------------------------------------------

class TestGitSourceFiltering:
    """Verify git-sourced entries are excluded from forge resolution."""

    def test_git_entries_not_in_forge_result(self):
        result = subprocess.run(
            ['python3', '-m', 'resolver', 'resolve', '/app/Puppetfile'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
        assert result.returncode == 0, f"Resolver failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert output['status'] == 'ok'
        module_names = [m['name'] for m in output['modules']]
        assert 'acme/profiles' not in module_names


# ---------------------------------------------------------------------------
# Circular dependency detection
# ---------------------------------------------------------------------------

class TestCircularDependency:
    """Verify circular dependencies are detected and reported."""

    def test_circular_detected(self):
        result = subprocess.run(
            ['python3', '-m', 'resolver', 'resolve', '/app/Puppetfile.circular'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
        output = json.loads(result.stdout)
        assert output['status'] == 'error', \
            f"Circular deps should fail, got: {output['status']}"
        assert output['error_type'] == 'circular_dependency', \
            f"Expected circular_dependency error, got: {output.get('error_type')}"
        assert 'cycle' in output, "Must include cycle path"
        assert len(output['cycle']) >= 3, \
            f"Cycle path too short: {output['cycle']}"
        assert output['cycle'][0] == output['cycle'][-1], \
            f"Cycle must start and end with same module: {output['cycle']}"
        # Both circular modules must appear in the cycle path
        cycle_modules = {e.split('@')[0] for e in output['cycle']}
        assert 'testorg/circular_a' in cycle_modules, \
            f"circular_a not in cycle: {output['cycle']}"
        assert 'testorg/circular_b' in cycle_modules, \
            f"circular_b not in cycle: {output['cycle']}"

    def test_circular_schema_validation(self):
        result = subprocess.run(
            ['python3', '-m', 'resolver', 'resolve', '/app/Puppetfile.circular'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
        jq_result = subprocess.run(
            ['jq', '-r', '-f', '/app/schema/cycle.jq'],
            input=result.stdout, capture_output=True, text=True, timeout=10
        )
        assert jq_result.returncode == 0, f"jq failed: {jq_result.stderr}"
        assert jq_result.stdout.strip() == 'valid', \
            f"Cycle schema validation failed: {jq_result.stdout.strip()}"

    def test_diamond_not_flagged_as_cycle(self):
        """Diamond dependencies (shared transitive dep) must resolve, not cycle."""
        from resolver.solver import Solver
        solver = Solver('/app/forge_db/modules.json')
        # apt and concat both depend on stdlib — this is a diamond, not a cycle
        result = solver.resolve([
            ('puppetlabs/apt', []),
            ('puppetlabs/concat', []),
        ])
        assert result['status'] == 'ok', \
            f"Diamond dependency incorrectly flagged as cycle: {result}"
        modules = {m['name']: m['version'] for m in result['modules']}
        assert 'puppetlabs/stdlib' in modules


# ---------------------------------------------------------------------------
# Integration: Production Puppetfile
# ---------------------------------------------------------------------------

class TestProductionResolution:
    """Verify production Puppetfile resolves with correct versions."""

    def test_production_versions(self):
        result = subprocess.run(
            ['python3', '-m', 'resolver', 'resolve', '/app/Puppetfile'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
        assert result.returncode == 0, f"Resolver failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert output['status'] == 'ok'
        modules = {m['name']: m['version'] for m in output['modules']}
        assert modules['puppetlabs/stdlib'] == '9.6.0'
        assert modules['puppetlabs/concat'] == '8.2.0'
        assert modules['puppetlabs/apt'] == '9.4.0'
        assert modules['voxpupuli/prometheus'] == '14.0.0'
        assert modules['voxpupuli/victorialogs'] == '1.0.0'
        assert modules['voxpupuli/systemd'] == '1.0.0'
        assert modules['voxpupuli/augeasproviders'] == '1.0.0'
        assert len(modules) == 7

    def test_production_lockfile(self):
        subprocess.run(
            ['python3', '-m', 'resolver', 'resolve', '/app/Puppetfile'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
        lockfile_path = '/app/Puppetfile.lock'
        assert os.path.exists(lockfile_path), "Puppetfile.lock was not generated"
        with open(lockfile_path) as f:
            lock = json.load(f)
        assert 'forge_modules' in lock
        assert 'git_modules' in lock
        forge_names = {m['name'] for m in lock['forge_modules']}
        assert 'puppetlabs/stdlib' in forge_names
        assert 'acme/profiles' not in forge_names
        git_names = {m['name'] for m in lock['git_modules']}
        assert 'acme/profiles' in git_names


# ---------------------------------------------------------------------------
# Integration: Staging Puppetfile
# ---------------------------------------------------------------------------

class TestStagingResolution:
    """Verify staging Puppetfile resolves the larger module graph correctly."""

    def test_staging_versions(self):
        result = subprocess.run(
            ['python3', '-m', 'resolver', 'resolve', '/app/Puppetfile.staging'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
        assert result.returncode == 0, f"Staging resolver failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert output['status'] == 'ok'
        modules = {m['name']: m['version'] for m in output['modules']}
        assert modules['puppetlabs/stdlib'] == '9.6.0'
        assert modules['puppetlabs/concat'] == '9.0.0'
        assert modules['puppetlabs/apt'] == '9.4.0'
        assert modules['voxpupuli/prometheus'] == '14.0.0'
        assert modules['voxpupuli/grafana_alloy'] == '2.0.0'
        assert modules['voxpupuli/nftables'] == '4.0.0'
        assert modules['voxpupuli/wireguard'] == '3.0.0'
        assert modules['puppetlabs/firewall'] == '7.0.0'
        assert modules['voxpupuli/k8s'] == '3.0.0'
        assert modules['voxpupuli/etcd'] == '3.0.0'
        assert modules['voxpupuli/vault'] == '5.0.0'
        assert modules['voxpupuli/hashi_stack'] == '3.0.0'
        assert len(modules) == 12


# ---------------------------------------------------------------------------
# Feature: Conflict explanation (--explain)
# ---------------------------------------------------------------------------

class TestConflictExplanation:
    """Verify --explain produces correct conflict diagnostics."""

    def test_explain_identifies_conflicts(self):
        result = subprocess.run(
            ['python3', '-m', 'resolver', 'resolve', '--explain',
             '/app/Puppetfile.conflict'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
        output = json.loads(result.stdout)
        assert output['status'] == 'error'
        assert 'conflicts' in output, "explain mode must produce conflicts key"
        assert len(output['conflicts']) > 0

        # Find the stdlib conflict
        stdlib_conflict = None
        for c in output['conflicts']:
            if 'stdlib' in c['module']:
                stdlib_conflict = c
                break
        assert stdlib_conflict is not None, \
            f"Expected conflict on stdlib, got: {output['conflicts']}"

        sources = [e['required_by'] for e in stdlib_conflict['unsatisfiable_constraints']]
        assert any('unsat_a' in s for s in sources), \
            f"Expected unsat_a in conflict sources: {sources}"
        assert any('unsat_b' in s for s in sources), \
            f"Expected unsat_b in conflict sources: {sources}"

    def test_explain_schema_validation(self):
        result = subprocess.run(
            ['python3', '-m', 'resolver', 'resolve', '--explain',
             '/app/Puppetfile.conflict'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
        jq_result = subprocess.run(
            ['jq', '-r', '-f', '/app/schema/explain.jq'],
            input=result.stdout, capture_output=True, text=True, timeout=10
        )
        assert jq_result.returncode == 0, f"jq failed: {jq_result.stderr}"
        assert jq_result.stdout.strip() == 'valid', \
            f"Explain schema validation failed: {jq_result.stdout.strip()}"


# ---------------------------------------------------------------------------
# Feature: DOT dependency graph (--graph)
# ---------------------------------------------------------------------------

class TestDependencyGraph:
    """Verify --graph produces valid DOT output renderable by graphviz."""

    def test_dot_graph_valid_and_renderable(self):
        dot_path = '/tmp/test_deps.dot'
        svg_path = '/tmp/test_deps.svg'
        for p in [dot_path, svg_path]:
            if os.path.exists(p):
                os.remove(p)

        result = subprocess.run(
            ['python3', '-m', 'resolver', 'resolve', '--graph', dot_path,
             '/app/Puppetfile'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
        assert result.returncode == 0, f"Resolver failed: {result.stderr}"
        assert os.path.exists(dot_path), "DOT file was not generated"

        # Verify graphviz can parse and render it
        dot_result = subprocess.run(
            ['dot', '-Tsvg', dot_path, '-o', svg_path],
            capture_output=True, text=True, timeout=10
        )
        assert dot_result.returncode == 0, \
            f"dot failed to render graph: {dot_result.stderr}"
        assert os.path.exists(svg_path), "SVG output was not generated"

    def test_dot_graph_content(self):
        dot_path = '/tmp/test_deps_content.dot'
        if os.path.exists(dot_path):
            os.remove(dot_path)

        subprocess.run(
            ['python3', '-m', 'resolver', 'resolve', '--graph', dot_path,
             '/app/Puppetfile'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
        with open(dot_path) as f:
            dot_content = f.read()

        assert 'digraph' in dot_content, "Must be a digraph"

        # All 7 resolved modules must appear as nodes
        expected_nodes = [
            'puppetlabs/stdlib@9.6.0',
            'puppetlabs/concat@8.2.0',
            'puppetlabs/apt@9.4.0',
            'voxpupuli/prometheus@14.0.0',
            'voxpupuli/victorialogs@1.0.0',
            'voxpupuli/augeasproviders@1.0.0',
            'voxpupuli/systemd@1.0.0',
        ]
        for node in expected_nodes:
            assert node in dot_content, \
                f"Module node '{node}' not found in DOT graph"

        # Must have dependency edges
        assert '->' in dot_content, "DOT graph must contain dependency edges"


# ---------------------------------------------------------------------------
# Feature: JSON schema validation via jq
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    """Verify resolution output passes jq schema validation."""

    def test_resolution_schema(self):
        result = subprocess.run(
            ['python3', '-m', 'resolver', 'resolve', '/app/Puppetfile'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
        assert result.returncode == 0
        jq_result = subprocess.run(
            ['jq', '-r', '-f', '/app/schema/resolution.jq'],
            input=result.stdout, capture_output=True, text=True, timeout=10
        )
        assert jq_result.returncode == 0, f"jq failed: {jq_result.stderr}"
        assert jq_result.stdout.strip() == 'valid', \
            f"Resolution schema validation failed: {jq_result.stdout.strip()}"
