
"""
Tests for C2 Teamserver Security Assessment with Custom Static Analysis.

Validates:
1. Bandit baseline output exists and is valid
2. Custom AST scanner detects vulns in original code, clean on patched
3. Assessment JSON conforms to schema with valid CVSS scoring
4. Exploit scripts work against original code
5. Patched files fix vulnerabilities while preserving functionality
"""

import pytest
import os
import sys
import json
import re
import math
import hashlib
import tempfile
import importlib.util
import subprocess


# ============================================================
# Helpers
# ============================================================

CVSS_VECTOR_RE = re.compile(
    r'^CVSS:3\.1/AV:([NALP])/AC:([LH])/PR:([NLH])/UI:([NR])'
    r'/S:([UC])/C:([NLH])/I:([NLH])/A:([NLH])$'
)


def compute_cvss_31_score(vector_str):
    """Compute CVSS 3.1 base score from a vector string."""
    m = CVSS_VECTOR_RE.match(vector_str)
    if not m:
        return None

    av, ac, pr, ui, s, c, i, a = m.groups()

    av_vals = {'N': 0.85, 'A': 0.62, 'L': 0.55, 'P': 0.20}
    ac_vals = {'L': 0.77, 'H': 0.44}
    ui_vals = {'N': 0.85, 'R': 0.62}
    cia_vals = {'H': 0.56, 'L': 0.22, 'N': 0.0}

    scope_changed = s == 'C'
    pr_vals = ({'N': 0.85, 'L': 0.68, 'H': 0.50} if scope_changed
               else {'N': 0.85, 'L': 0.62, 'H': 0.27})

    exploitability = (8.22 * av_vals[av] * ac_vals[ac]
                      * pr_vals[pr] * ui_vals[ui])
    iss = 1 - ((1 - cia_vals[c]) * (1 - cia_vals[i]) * (1 - cia_vals[a]))

    if iss <= 0:
        return 0.0

    if scope_changed:
        impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)
    else:
        impact = 6.42 * iss

    if impact <= 0:
        return 0.0

    if scope_changed:
        base = min(1.08 * (impact + exploitability), 10)
    else:
        base = min(impact + exploitability, 10)

    return math.ceil(base * 10) / 10


def severity_for_score(score):
    if score >= 9.0:
        return 'critical'
    elif score >= 7.0:
        return 'high'
    elif score >= 4.0:
        return 'medium'
    elif score > 0:
        return 'low'
    return 'none'


def load_module_from_path(module_name, file_path):
    """Dynamically load a Python module from a file path."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_test_accounts():
    return [
        {
            'username': 'svc_test',
            'password_hash': hashlib.sha256(b'test_password').hexdigest(),
            'role': 'service'
        },
        {
            'username': 'svc_readonly',
            'password_hash': hashlib.sha256(b'readonly_pass').hexdigest(),
            'role': 'readonly'
        }
    ]


def load_assessment():
    with open('/app/assessment.json') as f:
        return json.load(f)


def get_vulns(data):
    return data.get('vulnerabilities', [])


# ============================================================
# Test Group 1: Bandit Baseline
# ============================================================

class TestBanditBaseline:
    def test_baseline_exists(self):
        assert os.path.exists('/app/bandit_baseline.json'), \
            "bandit_baseline.json must exist at /app/bandit_baseline.json"

    def test_baseline_valid_json(self):
        with open('/app/bandit_baseline.json') as f:
            data = json.load(f)
        assert isinstance(data, dict), "Bandit output must be a JSON object"

    def test_baseline_has_results_key(self):
        with open('/app/bandit_baseline.json') as f:
            data = json.load(f)
        assert 'results' in data, "Bandit output must contain 'results' key"


# ============================================================
# Test Group 2: Custom Scanner
# ============================================================

class TestCustomScanner:
    def test_scanner_file_exists(self):
        assert os.path.exists('/app/scanner/vuln_scanner.py'), \
            "Custom scanner must exist at /app/scanner/vuln_scanner.py"

    def test_scanner_uses_ast_module(self):
        with open('/app/scanner/vuln_scanner.py') as f:
            source = f.read()
        assert 'import ast' in source or 'from ast' in source, \
            "Scanner must use the ast module"
        assert 'ast.parse' in source or 'ast.walk' in source or 'NodeVisitor' in source, \
            "Scanner must use AST parsing functionality"

    def test_scanner_produces_valid_json(self):
        result = subprocess.run(
            ['python3', '/app/scanner/vuln_scanner.py', '/app/teamserver/'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"Scanner must exit 0.\nstderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert 'findings' in data, "Scanner output must contain 'findings' key"
        assert isinstance(data['findings'], list)

    def test_scanner_detects_original_vulns(self):
        result = subprocess.run(
            ['python3', '/app/scanner/vuln_scanner.py', '/app/teamserver/'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        findings = data['findings']
        assert len(findings) >= 3, \
            f"Scanner should find >= 3 issues in original code, found {len(findings)}"

        # Check findings span multiple files
        files_with_findings = set(f['file'] for f in findings)
        assert len(files_with_findings) >= 3, \
            f"Findings should span >= 3 files, found in: {files_with_findings}"

    def test_scanner_clean_on_patched(self):
        result = subprocess.run(
            ['python3', '/app/scanner/vuln_scanner.py', '/app/patched/'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"Scanner must exit 0 on patched code.\nstderr: {result.stderr}"
        data = json.loads(result.stdout)
        findings = data['findings']
        assert len(findings) == 0, \
            f"Scanner should find 0 issues in patched code, found {len(findings)}: " \
            f"{json.dumps(findings, indent=2)}"

    def test_scanner_finding_schema(self):
        result = subprocess.run(
            ['python3', '/app/scanner/vuln_scanner.py', '/app/teamserver/'],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        for finding in data['findings']:
            assert 'file' in finding, "Each finding must have 'file'"
            assert 'line' in finding, "Each finding must have 'line'"
            assert 'rule_id' in finding, "Each finding must have 'rule_id'"
            assert 'severity' in finding, "Each finding must have 'severity'"
            assert 'message' in finding, "Each finding must have 'message'"
            assert finding['severity'] in ('critical', 'high', 'medium', 'low'), \
                f"Invalid severity: {finding['severity']}"


# ============================================================
# Test Group 3: Assessment Schema
# ============================================================

class TestAssessmentSchema:
    def test_assessment_exists(self):
        assert os.path.exists('/app/assessment.json'), \
            "assessment.json must exist at /app/assessment.json"

    def test_has_required_top_level_keys(self):
        data = load_assessment()
        for key in ['automated_baseline', 'vulnerabilities', 'attack_chains',
                     'remediation_priority']:
            assert key in data, f"Assessment must contain '{key}' key"

    def test_automated_baseline_schema(self):
        data = load_assessment()
        baseline = data['automated_baseline']
        for key in ['tool', 'total_findings', 'high_severity_count',
                     'coverage_gaps']:
            assert key in baseline, \
                f"automated_baseline must contain '{key}'"
        assert isinstance(baseline['total_findings'], int)
        assert isinstance(baseline['high_severity_count'], int)
        assert isinstance(baseline['coverage_gaps'], str)
        assert len(baseline['coverage_gaps']) > 20, \
            "coverage_gaps should be a substantial analysis"

    def test_vulnerability_schema(self):
        data = load_assessment()
        vulns = get_vulns(data)
        required_fields = [
            'id', 'cwe_id', 'title', 'affected_file', 'affected_function',
            'cvss_vector', 'cvss_score', 'severity_rating', 'description',
            'root_cause', 'detection_method'
        ]
        for v in vulns:
            for field in required_fields:
                assert field in v, \
                    f"Vulnerability {v.get('id', '?')} missing field '{field}'"
            assert isinstance(v['id'], int)
            assert isinstance(v['cvss_score'], (int, float))
            assert 0 <= v['cvss_score'] <= 10
            assert v['severity_rating'] in ('critical', 'high', 'medium', 'low')
            assert v['detection_method'] in ('automated', 'manual', 'both')
            assert re.match(r'^CWE-\d+$', v['cwe_id']), \
                f"Invalid CWE ID format: {v['cwe_id']}"

    def test_attack_chain_schema(self):
        data = load_assessment()
        chains = data['attack_chains']
        assert isinstance(chains, list)
        assert len(chains) >= 1, "Must have at least one attack chain"

        vuln_ids = {v['id'] for v in get_vulns(data)}
        for chain in chains:
            for key in ['chain_id', 'name', 'vulnerability_sequence',
                        'combined_impact', 'likelihood']:
                assert key in chain, f"Attack chain missing '{key}'"
            assert chain['likelihood'] in ('high', 'medium', 'low')
            assert isinstance(chain['vulnerability_sequence'], list)
            assert len(chain['vulnerability_sequence']) >= 2, \
                "Attack chain must reference at least 2 vulnerabilities"
            for vid in chain['vulnerability_sequence']:
                assert vid in vuln_ids, \
                    f"Chain references unknown vulnerability id {vid}"

    def test_remediation_priority(self):
        data = load_assessment()
        priority = data['remediation_priority']
        assert isinstance(priority, list)
        vuln_ids = {v['id'] for v in get_vulns(data)}
        for vid in priority:
            assert vid in vuln_ids, \
                f"remediation_priority references unknown id {vid}"
        assert set(priority) == vuln_ids, \
            "remediation_priority must cover all vulnerability ids"


# ============================================================
# Test Group 4: Vulnerability Identification
# ============================================================

class TestVulnerabilityIdentification:
    def test_at_least_four_vulnerabilities(self):
        data = load_assessment()
        vulns = get_vulns(data)
        assert len(vulns) >= 4, \
            f"Expected >= 4 vulnerabilities, found {len(vulns)}"

    def test_identifies_auth_bypass(self):
        data = load_assessment()
        vulns = get_vulns(data)
        found = any(
            ('287' in v.get('cwe_id', '') or 'auth' in v.get('title', '').lower())
            and 'auth' in v.get('affected_file', '').lower()
            for v in vulns
        )
        assert found, "Must identify authentication bypass (CWE-287) in auth.py"

    def test_identifies_builder_injection(self):
        data = load_assessment()
        vulns = get_vulns(data)
        found = any(
            ('78' in v.get('cwe_id', '') or 'inject' in v.get('title', '').lower())
            and 'builder' in v.get('affected_file', '').lower()
            for v in vulns
        )
        assert found, "Must identify command injection (CWE-78) in builder.py"

    def test_identifies_path_traversal(self):
        data = load_assessment()
        vulns = get_vulns(data)
        found = any(
            ('22' in v.get('cwe_id', '') or 'travers' in v.get('title', '').lower()
             or 'path' in v.get('title', '').lower())
            and 'handler' in v.get('affected_file', '').lower()
            for v in vulns
        )
        assert found, "Must identify path traversal (CWE-22) in handlers.py"

    def test_identifies_modules_injection(self):
        data = load_assessment()
        vulns = get_vulns(data)
        found = any(
            ('78' in v.get('cwe_id', '') or 'inject' in v.get('title', '').lower())
            and 'module' in v.get('affected_file', '').lower()
            for v in vulns
        )
        assert found, "Must identify command injection (CWE-78) in modules.py"


# ============================================================
# Test Group 5: CVSS Scoring
# ============================================================

class TestCVSSScoring:
    def test_cvss_vectors_valid_format(self):
        data = load_assessment()
        for v in get_vulns(data):
            vector = v['cvss_vector']
            assert CVSS_VECTOR_RE.match(vector), \
                f"Vuln {v['id']}: invalid CVSS vector format: {vector}"

    def test_cvss_scores_consistent_with_vectors(self):
        data = load_assessment()
        for v in get_vulns(data):
            vector = v['cvss_vector']
            reported = v['cvss_score']
            computed = compute_cvss_31_score(vector)
            assert computed is not None, \
                f"Vuln {v['id']}: could not compute score from vector"
            assert abs(reported - computed) <= 0.2, \
                f"Vuln {v['id']}: reported score {reported} != computed " \
                f"{computed} from vector {vector}"

    def test_severity_ratings_match_scores(self):
        data = load_assessment()
        for v in get_vulns(data):
            expected = severity_for_score(v['cvss_score'])
            actual = v['severity_rating']
            assert actual == expected, \
                f"Vuln {v['id']}: severity '{actual}' doesn't match " \
                f"score {v['cvss_score']} (expected '{expected}')"


# ============================================================
# Test Group 6: Original Vulnerabilities Exist
# ============================================================

class TestOriginalVulnerabilities:
    def test_auth_bypass_exists(self):
        auth_mod = load_module_from_path('orig_auth', '/app/teamserver/auth.py')
        accounts = make_test_accounts()
        authenticator = auth_mod.ServiceAuthenticator(accounts)
        result = authenticator.authenticate('nonexistent_user', 'any_password')
        assert result is None, \
            "Original auth should return None for unknown users"
        assert result is not False, \
            "None is not False — this enables the auth bypass"

    def test_builder_injection_exists(self):
        builder_mod = load_module_from_path('orig_builder',
                                            '/app/teamserver/builder.py')
        marker = '/tmp/test_orig_builder_marker'
        if os.path.exists(marker):
            os.remove(marker)
        builder = builder_mod.AgentBuilder(
            template_dir='/app/templates',
            output_dir='/tmp/test_orig_builder_out'
        )
        config = {
            'arch': 'x64', 'format': 'exe', 'protocol': 'https',
            'service_name': f'" -x; touch {marker}; #',
            'callback_host': '127.0.0.1', 'callback_port': 443,
        }
        try:
            builder.build(config)
        except Exception:
            pass
        assert os.path.exists(marker), \
            "Original builder.py must be vulnerable to command injection"
        os.remove(marker)

    def test_path_traversal_exists(self):
        handler_mod = load_module_from_path('orig_handlers',
                                            '/app/teamserver/handlers.py')
        with tempfile.TemporaryDirectory() as tmpdir:
            loot_dir = os.path.join(tmpdir, 'loot')
            handler = handler_mod.LootHandler(loot_dir=loot_dir)
            marker_path = os.path.join(tmpdir, 'traversal_marker')
            exploit_path = 'dummy/../../../../traversal_marker'
            handler.store_download('beacon1', exploit_path,
                                   b'traversal_success')
            assert os.path.exists(marker_path), \
                "Original handlers.py must be vulnerable to path traversal"

    def test_modules_injection_exists(self):
        modules_mod = load_module_from_path('orig_modules',
                                            '/app/teamserver/modules.py')
        marker = '/tmp/test_orig_modules_marker'
        if os.path.exists(marker):
            os.remove(marker)
        compiler = modules_mod.ModuleCompiler(modules_dir='/app/modules')
        beacon_info = {
            'arch': f'x64; touch {marker}; #',
            'os': 'windows'
        }
        try:
            compiler.compile_module('migrate', beacon_info)
        except Exception:
            pass
        assert os.path.exists(marker), \
            "Original modules.py must be vulnerable to command injection"
        os.remove(marker)


# ============================================================
# Test Group 7: Patches Fix Vulnerabilities
# ============================================================

class TestPatches:
    def test_patched_files_exist(self):
        for fname in ['auth.py', 'builder.py', 'handlers.py', 'modules.py']:
            path = f'/app/patched/{fname}'
            assert os.path.exists(path), f"Patched file must exist: {path}"

    def test_patched_auth_fixes_bypass(self):
        patched = load_module_from_path('patched_auth_fix',
                                        '/app/patched/auth.py')
        accounts = make_test_accounts()
        authenticator = patched.ServiceAuthenticator(accounts)
        try:
            result = authenticator.authenticate('nonexistent_user', 'any_pwd')
        except Exception:
            result = False
        assert not result, \
            "Patched auth must return falsy for unknown users"
        assert result is False, \
            "Patched auth must return exactly False (not None)"

    def test_patched_builder_fixes_injection(self):
        patched = load_module_from_path('patched_builder_fix',
                                        '/app/patched/builder.py')
        marker = '/tmp/test_patched_builder_marker'
        if os.path.exists(marker):
            os.remove(marker)
        builder = patched.AgentBuilder(
            template_dir='/app/templates',
            output_dir='/tmp/test_patched_builder_out'
        )
        config = {
            'arch': 'x64', 'format': 'exe', 'protocol': 'https',
            'service_name': f'" -x; touch {marker}; #',
            'callback_host': '127.0.0.1', 'callback_port': 443,
        }
        try:
            builder.build(config)
        except Exception:
            pass
        assert not os.path.exists(marker), \
            "Patched builder.py must prevent command injection"

    def test_patched_handlers_fixes_traversal(self):
        patched = load_module_from_path('patched_handlers_fix',
                                        '/app/patched/handlers.py')
        with tempfile.TemporaryDirectory() as tmpdir:
            loot_dir = os.path.join(tmpdir, 'loot')
            handler = patched.LootHandler(loot_dir=loot_dir)
            marker_path = os.path.join(tmpdir, 'traversal_marker')
            exploit_path = 'dummy/../../../../traversal_marker'
            try:
                handler.store_download('beacon1', exploit_path,
                                       b'traversal_attempt')
            except (ValueError, OSError):
                pass
            assert not os.path.exists(marker_path), \
                "Patched handlers.py must prevent path traversal"

    def test_patched_modules_fixes_injection(self):
        patched = load_module_from_path('patched_modules_fix',
                                        '/app/patched/modules.py')
        marker = '/tmp/test_patched_modules_marker'
        if os.path.exists(marker):
            os.remove(marker)
        compiler = patched.ModuleCompiler(modules_dir='/app/modules')
        beacon_info = {
            'arch': f'x64; touch {marker}; #',
            'os': 'windows'
        }
        try:
            compiler.compile_module('migrate', beacon_info)
        except Exception:
            pass
        assert not os.path.exists(marker), \
            "Patched modules.py must prevent command injection"


# ============================================================
# Test Group 8: Patches Preserve Functionality
# ============================================================

class TestPatchedFunctionality:
    def test_patched_auth_valid_login(self):
        patched = load_module_from_path('patched_auth_func',
                                        '/app/patched/auth.py')
        accounts = make_test_accounts()
        authenticator = patched.ServiceAuthenticator(accounts)
        result = authenticator.authenticate('svc_test', 'test_password')
        assert result is not None and result is not False, \
            "Valid credentials must authenticate successfully"
        assert result.get('authenticated') is True
        assert result.get('username') == 'svc_test'

    def test_patched_auth_wrong_password(self):
        patched = load_module_from_path('patched_auth_reject',
                                        '/app/patched/auth.py')
        accounts = make_test_accounts()
        authenticator = patched.ServiceAuthenticator(accounts)
        result = authenticator.authenticate('svc_test', 'wrong_password')
        assert result is False, "Wrong password must return False"

    def test_patched_builder_valid_config(self):
        patched = load_module_from_path('patched_builder_func',
                                        '/app/patched/builder.py')
        builder = patched.AgentBuilder(
            template_dir='/app/templates',
            output_dir='/tmp/test_patched_builder_legit'
        )
        config = {
            'arch': 'x64', 'format': 'exe', 'protocol': 'https',
            'service_name': 'WindowsUpdateService',
            'callback_host': '10.0.0.1', 'callback_port': 443,
        }
        try:
            result = builder.build(config)
            assert 'build_id' in result
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # Compiler not installed — acceptable

    def test_patched_handlers_valid_paths(self):
        patched = load_module_from_path('patched_handlers_func',
                                        '/app/patched/handlers.py')
        with tempfile.TemporaryDirectory() as tmpdir:
            loot_dir = os.path.join(tmpdir, 'loot')
            handler = patched.LootHandler(loot_dir=loot_dir)
            handler.store_download('beacon1',
                                   'Users/victim/Documents/secret.docx',
                                   b'data1')
            handler.store_download('beacon1',
                                   'home/user/.ssh/id_rsa',
                                   b'data2')
            downloads_dir = os.path.join(loot_dir, 'beacon1', 'downloads')
            assert os.path.exists(downloads_dir)
            stored = os.path.join(downloads_dir, 'Users', 'victim',
                                  'Documents', 'secret.docx')
            assert os.path.exists(stored), \
                "Legitimate paths must be stored correctly"

    def test_patched_modules_valid_arch(self):
        patched = load_module_from_path('patched_modules_func',
                                        '/app/patched/modules.py')
        compiler = patched.ModuleCompiler(modules_dir='/app/modules')
        for arch in ['x86', 'x64', 'arm', 'arm64']:
            try:
                result = compiler.compile_module(
                    'migrate', {'arch': arch, 'os': 'linux'})
                assert 'module' in result
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass  # Make may fail — acceptable


# ============================================================
# Test Group 9: Exploit Scripts
# ============================================================

class TestExploitScripts:
    def test_exploits_directory_exists(self):
        assert os.path.isdir('/app/exploits'), \
            "Exploits directory must exist at /app/exploits"

    def test_at_least_four_exploit_scripts(self):
        py_files = [f for f in os.listdir('/app/exploits')
                    if f.endswith('.py')]
        assert len(py_files) >= 4, \
            f"Expected >= 4 exploit scripts, found {len(py_files)}: {py_files}"

    def test_exploit_scripts_succeed(self):
        py_files = sorted(f for f in os.listdir('/app/exploits')
                          if f.endswith('.py'))
        for script in py_files:
            script_path = os.path.join('/app/exploits', script)
            result = subprocess.run(
                ['python3', script_path],
                capture_output=True, text=True,
                timeout=30, cwd='/app'
            )
            assert result.returncode == 0, \
                f"Exploit {script} must exit 0.\n" \
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
