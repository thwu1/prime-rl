#!/usr/bin/env python3

"""SP 800-185 FIPS certification pre-assessment solution.

Evaluates four vendor implementations, performs compound defect analysis,
assesses security impact, and generates corrected implementations.
"""

import json
import sys
import os
import importlib
import importlib.util

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/candidates')

with open('/app/test_vectors.json') as f:
    vectors = json.load(f)


def _load_temp_module(source, name):
    """Write source to temp file and import as module."""
    temp_path = f'/tmp/{name}.py'
    with open(temp_path, 'w') as f:
        f.write(source)
    spec = importlib.util.spec_from_file_location(name, temp_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    os.remove(temp_path)
    return mod


def run_cshake_tests(mod):
    """Test cSHAKE against all NIST vectors. Returns True if all pass."""
    for tv in vectors['cshake']:
        data = bytes.fromhex(tv['data'])
        N = tv['N'].encode()
        S = tv['S'].encode()
        try:
            result = mod.cshake(tv['security'], data, tv['output_bits'], N, S)
            if result.hex() != tv['expected']:
                return False
        except Exception:
            return False
    return True


def run_kmac_tests(mod):
    """Test KMAC against all NIST vectors. Returns True if all pass."""
    for tv in vectors['kmac']:
        key = bytes.fromhex(tv['key'])
        data = bytes.fromhex(tv['data'])
        S = tv['S'].encode()
        try:
            result = mod.kmac(tv['security'], key, data, tv['output_bits'], S)
            if result.hex() != tv['expected']:
                return False
        except Exception:
            return False
    return True


def run_tuplehash_tests(mod):
    """Test TupleHash against all NIST vectors. Returns True if all pass."""
    for tv in vectors['tuplehash']:
        tuples_data = [bytes.fromhex(t) for t in tv['tuples']]
        S = tv['S'].encode()
        try:
            result = mod.tuplehash(tv['security'], tuples_data,
                                    tv['output_bits'], S)
            if result.hex() != tv['expected']:
                return False
        except Exception:
            return False
    return True


def detect_compound_defects(vendor_source):
    """Fix only cSHAKE in the source, re-test KMAC and TupleHash.

    If KMAC/TupleHash still fail with corrected cSHAKE, they have compound
    defects (inherited + their own independent bug).
    """
    fixed = vendor_source.replace(
        "return _sponge(rate, prefix + X, 0x1F, L // 8)",
        "return _sponge(rate, prefix + X, 0x04, L // 8)"
    )
    try:
        mod = _load_temp_module(fixed, '_compound_check')
        kmac_ok = run_kmac_tests(mod)
        tuplehash_ok = run_tuplehash_tests(mod)
    except Exception:
        kmac_ok = False
        tuplehash_ok = False

    return {
        'kmac_still_fails': not kmac_ok,
        'tuplehash_still_fails': not tuplehash_ok
    }


def analyze_cshake_bug(source):
    """Identify specific cSHAKE construction error from source."""
    cshake_start = source.find('def cshake(')
    cshake_end = source.find('\ndef ', cshake_start + 10)
    cshake_body = source[cshake_start:cshake_end] if cshake_end > 0 else source[cshake_start:]

    if '0x04' not in cshake_body and '0x1F' in cshake_body:
        return ("Uses SHAKE domain separator byte 0x1F instead of cSHAKE-specific "
                "0x04 when N or S is non-empty, collapsing customized cSHAKE to "
                "plain SHAKE and breaking domain separation per SP 800-185 "
                "Section 6.2")
    return "Unknown cSHAKE construction error"


def analyze_kmac_bug(source):
    """Identify specific KMAC construction error from source."""
    kmac_start = source.find('def kmac(')
    kmac_end = source.find('\ndef ', kmac_start + 10)
    kmac_body = source[kmac_start:kmac_end] if kmac_end > 0 else source[kmac_start:]

    if 'left_encode(L)' in kmac_body:
        return ("Uses left_encode(L) instead of right_encode(L) for the output "
                "length encoding, violating SP 800-185 Section 8 step 4")
    if 'bytepad' not in kmac_body:
        return ("Omits bytepad() wrapper around encode_string(K), directly using "
                "the encoded key without rate-alignment, violating SP 800-185 "
                "Section 8 step 1")
    return "Unknown KMAC construction error"


def analyze_tuplehash_bug(source):
    """Identify specific TupleHash construction error from source."""
    th_start = source.find('def tuplehash(')
    th_body = source[th_start:]

    if 'join' in th_body and 'encode_string' in th_body:
        return ("Concatenates all input tuples into a single byte string before "
                "applying encode_string once, instead of applying encode_string "
                "to each tuple individually, destroying the unambiguous encoding "
                "property and enabling tuple boundary collision attacks per "
                "SP 800-185 Section 9")
    return "Unknown TupleHash construction error"


def generate_patch(vendor_name, source, cshake_ok, kmac_ok, tuplehash_ok):
    """Generate a corrected version of the vendor source by fixing identified bugs."""
    patched = source

    if not cshake_ok:
        patched = patched.replace(
            "return _sponge(rate, prefix + X, 0x1F, L // 8)",
            "return _sponge(rate, prefix + X, 0x04, L // 8)"
        )

    if not kmac_ok:
        # Fix left_encode → right_encode for output length
        kmac_start = patched.find('def kmac(')
        kmac_end = patched.find('\ndef ', kmac_start + 10)
        if kmac_end < 0:
            kmac_end = len(patched)
        kmac_section = patched[kmac_start:kmac_end]

        if 'left_encode(L)' in kmac_section:
            fixed_kmac = kmac_section.replace('left_encode(L)', 'right_encode(L)')
            patched = patched[:kmac_start] + fixed_kmac + patched[kmac_end:]

        # Fix missing bytepad for key encoding
        kmac_start = patched.find('def kmac(')
        kmac_end = patched.find('\ndef ', kmac_start + 10)
        if kmac_end < 0:
            kmac_end = len(patched)
        kmac_section = patched[kmac_start:kmac_end]

        if 'bytepad' not in kmac_section:
            patched = patched.replace(
                "new_X = encode_string(K) + X + right_encode(L)",
                "new_X = bytepad(encode_string(K), rate) + X + right_encode(L)"
            )

    if not tuplehash_ok:
        th_start = patched.find('def tuplehash(')
        th_body = patched[th_start:]
        if 'join' in th_body:
            patched = patched.replace(
                'Z = encode_string(b"".join(tuples))',
                'Z = b""\n    for Xi in tuples:\n        Z += encode_string(Xi)'
            )

    return patched


# ===== Main analysis =====

vendors = ['vendor_alpha', 'vendor_beta', 'vendor_gamma', 'vendor_delta']
report = {"candidates": {}, "selected_vendor": None}

os.makedirs('/app/patched', exist_ok=True)

for vendor in vendors:
    mod = importlib.import_module(vendor)

    cshake_ok = run_cshake_tests(mod)
    kmac_ok = run_kmac_tests(mod)
    tuplehash_ok = run_tuplehash_tests(mod)

    src_path = f'/app/candidates/{vendor}.py'
    with open(src_path) as f:
        source = f.read()

    defects = []

    # Compound detection for vendors with broken cSHAKE
    compound_info = None
    if not cshake_ok:
        compound_info = detect_compound_defects(source)

    # --- cSHAKE defect ---
    if not cshake_ok:
        cause = analyze_cshake_bug(source)
        defects.append({
            "function": "cshake",
            "classification": "independent",
            "inherited_from": None,
            "root_cause": cause,
            "security_impact": "critical"
        })

    # --- KMAC defect ---
    if not kmac_ok:
        if not cshake_ok:
            if compound_info and compound_info['kmac_still_fails']:
                own_cause = analyze_kmac_bug(source)
                defects.append({
                    "function": "kmac",
                    "classification": "compound",
                    "inherited_from": "cshake",
                    "root_cause": (f"Inherited cSHAKE domain separation defect, "
                                   f"plus independently: {own_cause.lower()}"),
                    "security_impact": "high"
                })
            else:
                defects.append({
                    "function": "kmac",
                    "classification": "inherited",
                    "inherited_from": "cshake",
                    "root_cause": ("KMAC calls cSHAKE internally; failure "
                                   "inherited from non-conformant cSHAKE"),
                    "security_impact": None
                })
        else:
            cause = analyze_kmac_bug(source)
            defects.append({
                "function": "kmac",
                "classification": "independent",
                "inherited_from": None,
                "root_cause": cause,
                "security_impact": "high"
            })

    # --- TupleHash defect ---
    if not tuplehash_ok:
        if not cshake_ok:
            if compound_info and compound_info['tuplehash_still_fails']:
                own_cause = analyze_tuplehash_bug(source)
                defects.append({
                    "function": "tuplehash",
                    "classification": "compound",
                    "inherited_from": "cshake",
                    "root_cause": (f"Inherited cSHAKE defect, plus independently: "
                                   f"{own_cause.lower()}"),
                    "security_impact": "critical"
                })
            else:
                defects.append({
                    "function": "tuplehash",
                    "classification": "inherited",
                    "inherited_from": "cshake",
                    "root_cause": ("TupleHash calls cSHAKE internally; failure "
                                   "inherited from non-conformant cSHAKE"),
                    "security_impact": None
                })
        else:
            cause = analyze_tuplehash_bug(source)
            defects.append({
                "function": "tuplehash",
                "classification": "independent",
                "inherited_from": None,
                "root_cause": cause,
                "security_impact": "critical"
            })

    all_pass = cshake_ok and kmac_ok and tuplehash_ok
    recommendation = "deploy" if all_pass else "reject"

    report['candidates'][vendor] = {
        "cshake": "pass" if cshake_ok else "fail",
        "kmac": "pass" if kmac_ok else "fail",
        "tuplehash": "pass" if tuplehash_ok else "fail",
        "defects": defects,
        "recommendation": recommendation
    }

    if all_pass:
        report['selected_vendor'] = vendor
    else:
        patched = generate_patch(vendor, source, cshake_ok, kmac_ok, tuplehash_ok)
        with open(f'/app/patched/{vendor}.py', 'w') as f:
            f.write(patched)

    status = "CONFORMANT" if all_pass else "NON-CONFORMANT"
    print(f"{vendor}: {status}")
    if defects:
        for d in defects:
            trunc = d['root_cause'][:90]
            print(f"  {d['function']}: {d['classification']} "
                  f"(impact: {d['security_impact']}) - {trunc}...")

with open('/app/audit_report.json', 'w') as f:
    json.dump(report, f, indent=2)

print(f"\nSelected vendor: {report['selected_vendor']}")
print("Report written to /app/audit_report.json")
print("Patched implementations written to /app/patched/")

# Verify patches
print("\n=== Verifying patches ===")
for vendor in ['vendor_alpha', 'vendor_beta', 'vendor_delta']:
    patch_path = f'/app/patched/{vendor}.py'
    if os.path.exists(patch_path):
        spec = importlib.util.spec_from_file_location(
            f'verify_{vendor}', patch_path)
        pmod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pmod)
        cs = run_cshake_tests(pmod)
        km = run_kmac_tests(pmod)
        th = run_tuplehash_tests(pmod)
        ok = cs and km and th
        print(f"  {vendor} patch: {'ALL PASS' if ok else 'FAIL'} "
              f"(cSHAKE={cs}, KMAC={km}, TupleHash={th})")
