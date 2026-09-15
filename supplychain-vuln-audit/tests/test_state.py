"""
Supply chain security audit verification tests.

Verifies that the agent correctly identified all vulnerabilities,
produced valid SARIF output, captured DNS exfiltration evidence,
wrote working exploits, analyzed the backdoor, and applied fixes.

"""

import json
import subprocess
import os
import re


# ---------------------------------------------------------------------------
# SARIF report tests
# ---------------------------------------------------------------------------

def test_sarif_report_structure():
    """SARIF report must be valid v2.1.0 with proper structure."""
    assert os.path.exists('/app/sarif_report.json'), "sarif_report.json not found"
    with open('/app/sarif_report.json') as f:
        sarif = json.load(f)

    assert sarif.get('version') == '2.1.0', \
        f"SARIF version must be '2.1.0', got '{sarif.get('version')}'"
    assert '$schema' in sarif, "SARIF must have $schema field"

    runs = sarif.get('runs', [])
    assert len(runs) >= 1, "SARIF must have at least one run"

    run = runs[0]
    tool = run.get('tool', {})
    driver = tool.get('driver', {})
    assert 'name' in driver, "Tool driver must have a name"

    rules = driver.get('rules', [])
    assert len(rules) >= 4, f"Should have at least 4 rules, got {len(rules)}"

    results = run.get('results', [])
    assert len(results) >= 5, f"Should have at least 5 results, got {len(results)}"


def test_sarif_result_fields():
    """Each SARIF result must have ruleId, level, message, and locations."""
    with open('/app/sarif_report.json') as f:
        sarif = json.load(f)

    results = sarif['runs'][0]['results']
    for i, r in enumerate(results):
        assert 'ruleId' in r, f"Result {i} missing ruleId"
        assert 'level' in r, f"Result {i} missing level"
        assert 'message' in r, f"Result {i} missing message"
        assert 'locations' in r and len(r['locations']) > 0, \
            f"Result {i} missing locations"
        loc = r['locations'][0]
        phys = loc.get('physicalLocation', {})
        assert 'artifactLocation' in phys, \
            f"Result {i} missing artifactLocation in physicalLocation"


def test_sarif_covers_vulnerabilities():
    """SARIF results must reference all vulnerability classes."""
    with open('/app/sarif_report.json') as f:
        sarif = json.load(f)

    all_text = json.dumps(sarif).lower()

    checks = [
        ('Prototype Pollution (CWE-1321)',
         ['1321', 'prototype pollution', 'proto pollution']),
        ('Command Injection (CWE-77/78)',
         ['cwe-77', 'cwe-78', 'command injection', 'shell injection']),
        ('ReDoS (CWE-1333)',
         ['1333', 'redos', 'denial of service', 'backtrack']),
        ('Path Traversal (CWE-22)',
         ['cwe-22', 'cwe-59', 'path traversal', 'symlink', 'directory traversal']),
        ('Backdoor (CWE-506)',
         ['506', 'backdoor', 'malicious code', 'supply chain']),
    ]

    for name, terms in checks:
        assert any(t in all_text for t in terms), \
            f"SARIF should reference {name}. Terms checked: {terms}"


# ---------------------------------------------------------------------------
# DNS exfiltration log tests
# ---------------------------------------------------------------------------

def _extract_queries(data):
    """Extract DNS query records from the exfil log, tolerating format variations."""
    for key in ['intercepted_queries', 'queries', 'dns_queries', 'records']:
        if key in data and isinstance(data[key], list):
            return data[key]
    for val in data.values():
        if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
            if any(k in val[0] for k in ['hostname', 'name', 'query', 'domain', 'qname']):
                return val
    return []


def _extract_hostnames(queries):
    """Extract hostname strings from query records."""
    hostnames = []
    for q in queries:
        for key in ['hostname', 'name', 'query', 'domain', 'qname']:
            if key in q and isinstance(q[key], str):
                hostnames.append(q[key])
    return hostnames


def test_dns_exfil_log_exists():
    """DNS exfiltration log must exist and be valid JSON."""
    assert os.path.exists('/app/dns_exfil_log.json'), "dns_exfil_log.json not found"
    size = os.path.getsize('/app/dns_exfil_log.json')
    assert size > 50, \
        f"dns_exfil_log.json too small ({size} bytes) - likely empty"
    with open('/app/dns_exfil_log.json') as f:
        data = json.load(f)
    assert isinstance(data, dict), "dns_exfil_log.json should be a JSON object"


def test_dns_exfil_log_has_queries():
    """DNS exfiltration log must contain multiple captured query records."""
    with open('/app/dns_exfil_log.json') as f:
        data = json.load(f)
    queries = _extract_queries(data)
    assert len(queries) >= 2, \
        f"Expected >= 2 captured DNS queries, got {len(queries)}. Keys: {list(data.keys())}"


def test_dns_exfil_log_evidence():
    """DNS queries must show hex-encoded exfiltration to the backdoor C2 domain."""
    with open('/app/dns_exfil_log.json') as f:
        data = json.load(f)
    queries = _extract_queries(data)
    hostnames = _extract_hostnames(queries)
    all_hostnames = ' '.join(hostnames).lower()
    full_text = json.dumps(data).lower()

    # The decoded C2 domain is collect.evil-telemetry.net
    domain_found = any(t in full_text for t in [
        'evil', 'telemetry.net', 'collect.evil',
    ])
    assert domain_found, \
        f"Queries should reference the backdoor C2 domain. Sample: {full_text[:500]}"

    # Queries must contain hex-encoded exfiltrated data (env vars)
    hex_pat = re.compile(r'[0-9a-f]{10,}')
    has_hex = bool(hex_pat.search(all_hostnames))
    assert has_hex, \
        f"DNS query hostnames should contain hex-encoded data. Hostnames: {all_hostnames[:500]}"


# ---------------------------------------------------------------------------
# Audit report tests
# ---------------------------------------------------------------------------

def test_audit_report_structure():
    """Audit report exists, is a JSON array with at least 5 findings."""
    assert os.path.exists('/app/audit_report.json'), "audit_report.json not found"
    with open('/app/audit_report.json') as f:
        report = json.load(f)
    assert isinstance(report, list), "Report should be a JSON array"
    assert len(report) >= 5, f"Should have at least 5 findings, got {len(report)}"
    for finding in report:
        assert isinstance(finding, dict), "Each finding should be a dict"


def _extract_cwes(report):
    """Extract all CWE IDs from the report, normalized to numbers."""
    cwes = set()
    for finding in report:
        for key in ['cwe_id', 'cwe', 'cwe_ids', 'cwes', 'vulnerability_type']:
            val = finding.get(key)
            if val is None:
                continue
            vals = val if isinstance(val, list) else [val]
            for v in vals:
                s = str(v).upper().strip()
                m = re.search(r'(\d{2,4})', s)
                if m:
                    cwes.add(m.group(1))
    return cwes


def test_audit_report_cwes():
    """Report must identify all five vulnerability classes."""
    with open('/app/audit_report.json') as f:
        report = json.load(f)
    cwes = _extract_cwes(report)

    assert any(c in cwes for c in ['1321']), \
        f"Missing CWE-1321 (Prototype Pollution). Found CWEs: {cwes}"
    assert any(c in cwes for c in ['77', '78']), \
        f"Missing CWE-77 (Command Injection). Found CWEs: {cwes}"
    assert any(c in cwes for c in ['1333', '400']), \
        f"Missing CWE-1333 (ReDoS). Found CWEs: {cwes}"
    assert any(c in cwes for c in ['22', '59', '23']), \
        f"Missing CWE-22 (Path Traversal). Found CWEs: {cwes}"
    assert any(c in cwes for c in ['506', '94', '912']), \
        f"Missing CWE-506 (Malicious Code). Found CWEs: {cwes}"


def test_audit_report_modules():
    """Report must reference all five modules."""
    with open('/app/audit_report.json') as f:
        report = json.load(f)

    all_text = json.dumps(report).lower().replace('-', '_').replace(' ', '_')

    assert 'config_flatten' in all_text, "Should mention config-flatten"
    assert 'cmd_builder' in all_text or 'command_builder' in all_text, \
        "Should mention cmd-builder"
    assert 'input_validator' in all_text, "Should mention input-validator"
    assert 'archive_utils' in all_text, "Should mention archive-utils"
    assert 'telemetry' in all_text, "Should mention telemetry-helper"


# ---------------------------------------------------------------------------
# Exploit script existence
# ---------------------------------------------------------------------------

def test_exploit_scripts_exist():
    """At least 4 exploit .js scripts must exist in /app/exploits/."""
    exploits_dir = '/app/exploits'
    assert os.path.isdir(exploits_dir), "/app/exploits directory not found"
    js_files = [f for f in os.listdir(exploits_dir) if f.endswith('.js')]
    assert len(js_files) >= 4, \
        f"Expected >= 4 exploit scripts, found {len(js_files)}: {js_files}"


# ---------------------------------------------------------------------------
# Original-code vulnerability sanity checks
# ---------------------------------------------------------------------------

def _run_node(code, timeout=30):
    """Run inline Node.js code and return the CompletedProcess."""
    return subprocess.run(
        ['node', '-e', code],
        capture_output=True, text=True, timeout=timeout, cwd='/app',
    )


def test_original_proto_pollution():
    """Original config-flatten must be vulnerable to prototype pollution."""
    r = _run_node('''
const { unflatten } = require('/app/.originals/config-flatten');
delete Object.prototype._test_pp;
unflatten({"__proto__._test_pp": "yes"});
if (({})._test_pp === "yes") {
    delete Object.prototype._test_pp;
    process.exit(0);
}
process.exit(1);
''')
    assert r.returncode == 0, \
        f"Original config-flatten should be vulnerable: {r.stderr}"


def test_original_cmd_injection():
    """Original cmd-builder must pass backtick-colon-backslash through unescaped."""
    r = _run_node(r'''
const { quote } = require('/app/.originals/cmd-builder');
const result = quote(["`:\\test"]);
if (result === "`:\\test") {
    process.exit(0);
}
process.exit(1);
''')
    assert r.returncode == 0, \
        f"Original cmd-builder should be vulnerable: {r.stdout} {r.stderr}"


def test_original_redos():
    """Original input-validator must exhibit catastrophic backtracking."""
    r = _run_node('''
const { validateEmail } = require('/app/.originals/input-validator');
const start = Date.now();
validateEmail("a".repeat(30) + "!@b.com");
const elapsed = Date.now() - start;
process.exit(elapsed > 500 ? 0 : 1);
''', timeout=120)
    assert r.returncode == 0, \
        f"Original input-validator should be vulnerable to ReDoS: {r.stdout} {r.stderr}"


def test_original_path_traversal():
    """Original archive-utils must allow symlink-based path traversal."""
    r = _run_node('''
const { extractArchive } = require('/app/.originals/archive-utils');
const fs = require('fs');
const os = require('os');
const path = require('path');
const destDir = fs.mkdtempSync(path.join(os.tmpdir(), 'tv-'));
const escape = path.join(os.tmpdir(), '_tb_escape_orig.txt');
try { fs.unlinkSync(escape); } catch(e) {}
extractArchive([
    { name: "sub", type: "directory" },
    { name: "sub", type: "symlink", target: os.tmpdir() },
    { name: "sub/_tb_escape_orig.txt", type: "file", content: "ESC" }
], destDir);
if (fs.existsSync(escape) && fs.readFileSync(escape,'utf8') === 'ESC') {
    fs.unlinkSync(escape);
    fs.rmSync(destDir, { recursive: true, force: true });
    process.exit(0);
}
fs.rmSync(destDir, { recursive: true, force: true });
process.exit(1);
''')
    assert r.returncode == 0, \
        f"Original archive-utils should be vulnerable: {r.stdout} {r.stderr}"


# ---------------------------------------------------------------------------
# Fix verification
# ---------------------------------------------------------------------------

def test_fixed_proto_pollution():
    """Fixed config-flatten must not pollute Object.prototype."""
    r = _run_node('''
const { unflatten } = require('/app/lib/config-flatten');
delete Object.prototype._fix_pp;
delete Object.prototype._fix_cp;
try { unflatten({"__proto__._fix_pp": "yes"}); } catch(e) {}
try { unflatten({"constructor.prototype._fix_cp": true}); } catch(e) {}
if (({})._fix_pp === "yes" || ({})._fix_cp === true) {
    delete Object.prototype._fix_pp;
    delete Object.prototype._fix_cp;
    process.exit(1);
}
process.exit(0);
''')
    assert r.returncode == 0, f"config-flatten should be fixed: {r.stdout}"


def test_fixed_cmd_injection():
    """Fixed cmd-builder must escape or quote backtick-colon-backslash input."""
    r = _run_node(r'''
const { quote } = require('/app/lib/cmd-builder');
const result = quote(["`:\\test"]);
if (result === "`:\\test") {
    process.exit(1);
}
process.exit(0);
''')
    assert r.returncode == 0, f"cmd-builder should be fixed: {r.stdout}"


def test_fixed_redos():
    """Fixed input-validator must not exhibit catastrophic backtracking."""
    r = _run_node('''
const { validateEmail } = require('/app/lib/input-validator');
const start = Date.now();
try { validateEmail("a".repeat(30) + "!@b.com"); } catch(e) {}
const elapsed = Date.now() - start;
process.exit(elapsed < 2000 ? 0 : 1);
''', timeout=15)
    assert r.returncode == 0, \
        f"input-validator ReDoS should be fixed: {r.stdout}"


def test_fixed_path_traversal():
    """Fixed archive-utils must block symlink-based path traversal."""
    r = _run_node('''
const { extractArchive } = require('/app/lib/archive-utils');
const fs = require('fs');
const os = require('os');
const path = require('path');
const destDir = fs.mkdtempSync(path.join(os.tmpdir(), 'tv-'));
const escape = path.join(os.tmpdir(), '_tb_escape_fix.txt');
try { fs.unlinkSync(escape); } catch(e) {}
try {
    extractArchive([
        { name: "sub", type: "directory" },
        { name: "sub", type: "symlink", target: os.tmpdir() },
        { name: "sub/_tb_escape_fix.txt", type: "file", content: "ESC" }
    ], destDir);
} catch(e) {}
const escaped = fs.existsSync(escape);
if (escaped) { try { fs.unlinkSync(escape); } catch(e) {} }
fs.rmSync(destDir, { recursive: true, force: true });
process.exit(escaped ? 1 : 0);
''')
    assert r.returncode == 0, \
        f"archive-utils path traversal should be fixed: {r.stdout}"


# ---------------------------------------------------------------------------
# Backdoor analysis
# ---------------------------------------------------------------------------

def test_backdoor_analysis():
    """Backdoor analysis must identify DNS exfiltration and env var theft."""
    assert os.path.exists('/app/backdoor_analysis.json'), \
        "backdoor_analysis.json not found"
    with open('/app/backdoor_analysis.json') as f:
        analysis = json.load(f)
    content = json.dumps(analysis).lower()

    assert 'dns' in content, "Should identify DNS exfiltration technique"

    env_terms = [
        'environment variable', 'env var', 'process.env', 'secret',
        'token', 'credential', 'password', 'api key', 'aws', 'sensitive',
    ]
    assert any(t in content for t in env_terms), \
        f"Should identify env var theft. Content: {content[:500]}"

    domain_terms = [
        'evil', 'telemetry', '.net', '.xyz', 'charcode', 'fromcharcode',
        'obfuscat', 'encoded', 'c2', 'command and control', 'exfil',
    ]
    assert any(t in content for t in domain_terms), \
        f"Should identify C2 domain or obfuscation. Content: {content[:500]}"


def test_backdoor_removed():
    """Malicious code must be removed from telemetry-helper source."""
    telemetry_path = '/app/lib/telemetry-helper/index.js'
    assert os.path.exists(telemetry_path), \
        "telemetry-helper/index.js should still exist (preserve legitimate API)"

    with open(telemetry_path) as f:
        content = f.read()

    assert 'fromCharCode' not in content, \
        "String.fromCharCode obfuscation should be removed"

    assert '_payload' not in content and '_chunks' not in content, \
        "DNS exfiltration payload/chunk variables should be removed"
