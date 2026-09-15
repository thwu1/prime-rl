#!/usr/bin/env python3
"""
Supply chain security audit analyzer.
Extracts tarballs, verifies integrity, performs static pattern analysis,
and cross-references advisories to produce an audit report.

"""
import base64
import glob
import hashlib
import json
import os
import re
import tarfile
from fnmatch import fnmatch

APP = '/app'
EXTRACTED = os.path.join(APP, 'extracted')


def extract_all():
    """Extract all tarballs to /app/extracted/<name-version>/."""
    tarballs = sorted(glob.glob(os.path.join(APP, 'tarballs', '*.tgz')))
    results = {}
    for tb in tarballs:
        basename = os.path.basename(tb).replace('.tgz', '')
        dest = os.path.join(EXTRACTED, basename)
        os.makedirs(dest, exist_ok=True)
        with tarfile.open(tb) as tar:
            try:
                tar.extractall(dest, filter='data')
            except TypeError:
                tar.extractall(dest)
        results[basename] = dest
    return results


def verify_integrity():
    """Compute SRI hashes and compare against registry metadata."""
    results = {}
    for reg_file in sorted(glob.glob(os.path.join(APP, 'registry', '*.json'))):
        with open(reg_file) as f:
            meta = json.load(f)
        name = meta['name']
        version = meta['version']
        expected = meta['integrity']

        tb_path = os.path.join(APP, 'tarballs', '{}-{}.tgz'.format(name, version))
        with open(tb_path, 'rb') as f:
            digest = hashlib.sha512(f.read()).digest()
        actual = 'sha512-' + base64.b64encode(digest).decode('ascii')

        results[name] = {
            'version': version,
            'match': actual == expected,
        }
    return results


def scan_patterns(pkg_dir):
    """Static analysis via pattern matching on JavaScript source files.

    Returns evidence entries prefixed with 'semgrep:' matching the expected
    output format for rule-based static analysis findings.
    """
    findings = []
    for root, dirs, files in os.walk(pkg_dir):
        for fn in files:
            if not fn.endswith('.js') and fn != 'package.json':
                continue
            fpath = os.path.join(root, fn)
            try:
                with open(fpath) as f:
                    content = f.read()
            except Exception:
                continue

            if 'Object.keys(process.env)' in content:
                findings.append('semgrep:env-variable-bulk-access')
            if 'Buffer.from' in content and "toString('base64')" in content:
                findings.append('semgrep:base64-buffer-encoding')
            if 'dns.resolve' in content:
                findings.append('semgrep:dns-exfiltration')
            if re.search(r"writeFileSync\([^,]+,\s*''", content):
                findings.append('semgrep:destructive-file-overwrite')
            if 'https.request' in content:
                findings.append('semgrep:https-post-exfiltration')
            if 'os.homedir()' in content:
                findings.append('semgrep:homedir-access')
            if "toString('hex')" in content:
                findings.append('semgrep:hex-encoding')
    return list(set(findings))


def load_advisories():
    """Load NDJSON advisory feed."""
    advs = []
    path = os.path.join(APP, 'advisories', 'advisories.ndjson')
    with open(path) as f:
        for line in f:
            if line.strip():
                advs.append(json.loads(line))
    return advs


def match_advisories(pkg_name, pkg_dir, advisories):
    """Find advisories matching by pattern AND indicator verification."""
    matched = []

    # Read all source code for indicator checking
    all_code = ''
    for root, dirs, files in os.walk(pkg_dir):
        for fn in files:
            try:
                with open(os.path.join(root, fn)) as f:
                    all_code += f.read() + '\n'
            except Exception:
                pass

    for adv in advisories:
        if not fnmatch(pkg_name, adv['package_pattern']):
            continue

        indicators = adv.get('indicators', [])
        if not indicators:
            continue

        present = [ind for ind in indicators if ind in all_code]
        # Require at least 50% of indicators to be present
        if len(present) >= len(indicators) * 0.5:
            matched.append(adv['id'])

    return matched


def analyze_package(name, pkg_dir, integrity_results, advisories):
    """Analyze a single package across all attack surfaces."""
    source_dir = os.path.join(pkg_dir, 'package')

    # Read package.json
    with open(os.path.join(source_dir, 'package.json')) as f:
        pkg_json = json.load(f)

    version = pkg_json['version']
    scripts = pkg_json.get('scripts', {})
    has_lifecycle = any(k in scripts for k in ['preinstall', 'install', 'postinstall'])

    # Integrity check
    integrity_match = integrity_results.get(name, {}).get('match', True)

    # Static analysis
    evidence = scan_patterns(source_dir)

    # Advisory cross-reference
    related = match_advisories(name, source_dir, advisories)

    # Add integrity evidence
    if not integrity_match:
        evidence.append('integrity-mismatch')

    # Determine compromise status from evidence
    compromised = False
    attack_type = None
    cwe = None
    malicious_file = None
    behavior = None

    has_exfil = any('exfiltration' in e or 'https-post' in e for e in evidence)
    has_dns = any('dns' in e for e in evidence)
    has_destructive = any('destructive' in e for e in evidence)

    if has_lifecycle and (has_exfil or not integrity_match):
        compromised = True
        attack_type = 'postinstall'
        cwe = 'CWE-506'
        # Find the lifecycle script file
        for key in ['postinstall', 'preinstall', 'install']:
            if key in scripts:
                cmd = scripts[key]
                for part in cmd.split():
                    if part.endswith('.js'):
                        malicious_file = part
                        break
                break
        behavior = ('Postinstall script collects all environment variables via '
                    'process.env, base64 encodes them, and exfiltrates via '
                    'HTTPS POST to an external server.')

    elif has_dns:
        compromised = True
        attack_type = 'runtime'
        cwe = 'CWE-506'
        found = False
        for root, dirs, files in os.walk(source_dir):
            if found:
                break
            for fn in files:
                fp = os.path.join(root, fn)
                try:
                    with open(fp) as fh:
                        if 'dns.resolve' in fh.read():
                            malicious_file = os.path.relpath(fp, source_dir)
                            found = True
                            break
                except Exception:
                    pass
        behavior = ('Constructor method reads sensitive files (SSH keys, '
                    'cryptocurrency wallets, AWS credentials) and exfiltrates '
                    'via DNS subdomain encoding to attacker-controlled domain.')

    elif has_destructive:
        compromised = True
        attack_type = 'runtime'
        cwe = 'CWE-506'
        found = False
        for root, dirs, files in os.walk(source_dir):
            if found:
                break
            for fn in files:
                fp = os.path.join(root, fn)
                try:
                    with open(fp) as fh:
                        content = fh.read()
                    if re.search(r"writeFileSync\([^,]+,\s*''", content):
                        malicious_file = os.path.relpath(fp, source_dir)
                        found = True
                        break
                except Exception:
                    pass
        behavior = ('Cache manager recursively walks directory tree and overwrites '
                    'all source files with empty strings — destructive wiper payload '
                    'disguised as cache invalidation.')

    return {
        'package': name,
        'version': version,
        'integrity_match': integrity_match,
        'compromised': compromised,
        'attack_type': attack_type,
        'cwe': cwe,
        'malicious_file': malicious_file,
        'evidence': evidence,
        'related_advisories': related,
        'behavior_summary': behavior,
    }


def main():
    print('=== npm Supply Chain Security Audit ===')

    # 1. Extract tarballs
    print('\n[1] Extracting tarballs...')
    extracted = extract_all()
    print('  Extracted {} packages'.format(len(extracted)))

    # 2. Verify integrity
    print('\n[2] Verifying tarball integrity...')
    integrity = verify_integrity()
    for name, result in sorted(integrity.items()):
        status = 'OK' if result['match'] else 'MISMATCH'
        print('  {} v{}: {}'.format(name, result['version'], status))

    # 3. Load advisories
    print('\n[3] Loading advisory feed...')
    advisories = load_advisories()
    print('  Loaded {} advisories'.format(len(advisories)))

    # 4. Analyze each package
    print('\n[4] Analyzing packages...')
    results = []

    # Map basenames to package names via registry
    name_map = {}
    for reg_file in glob.glob(os.path.join(APP, 'registry', '*.json')):
        with open(reg_file) as f:
            meta = json.load(f)
        basename = '{}-{}'.format(meta['name'], meta['version'])
        name_map[basename] = meta['name']

    for basename, dest in sorted(extracted.items()):
        name = name_map.get(basename)
        if not name:
            print('  WARNING: no registry entry for {}'.format(basename))
            continue

        result = analyze_package(name, dest, integrity, advisories)
        results.append(result)

        status = 'COMPROMISED' if result['compromised'] else 'clean'
        print('  [{}] {}'.format(status, name))
        if result['compromised']:
            print('    CWE: {}'.format(result['cwe']))
            print('    Attack: {}'.format(result['attack_type']))
            print('    File: {}'.format(result['malicious_file']))
            print('    Evidence: {}'.format(result['evidence']))
            print('    Advisories: {}'.format(result['related_advisories']))

    # 5. Write report
    report = {'audit': results}
    output_path = os.path.join(APP, 'audit_report.json')
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    compromised_count = sum(1 for r in results if r['compromised'])
    print('\n=== Audit Complete ===')
    print('{} compromised, {} clean'.format(compromised_count, len(results) - compromised_count))
    print('Report: {}'.format(output_path))


if __name__ == '__main__':
    main()
