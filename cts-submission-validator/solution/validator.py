#!/usr/bin/env python3
"""VK-GL-CTS Conformance Submission Audit — full validator."""

import os
import re
import json
import glob
import gzip
import tarfile
import fnmatch
import xml.etree.ElementTree as ET
from collections import defaultdict

DATA_DIR = "/data"

# Status severity ordering (index = severity level, higher = more severe)
STATUS_SEVERITY = [
    "Pass", "NotSupported", "QualityWarning", "CompatibilityWarning",
    "Fail", "InternalError", "Crash", "ResourceError"
]

ALLOWED_STATUSES = frozenset({
    "Pass", "NotSupported", "QualityWarning", "CompatibilityWarning", "Waiver"
})


def severity_of(status):
    """Return severity index (higher = more severe)."""
    try:
        return STATUS_SEVERITY.index(status)
    except ValueError:
        return len(STATUS_SEVERITY)


def parse_version(version_str):
    """Parse CTS version string like 'vulkan-cts-1.3.8.0' into comparable tuple."""
    m = re.search(r'(\d+(?:\.\d+)*)', version_str)
    if m:
        return tuple(int(x) for x in m.group(1).split('.'))
    return ()


def parse_qpa_file(filepath):
    """Parse a QPA file, returning (results_list, session_info_dict)."""
    with open(filepath) as f:
        content = f.read()

    session_info = {}
    for m in re.finditer(r'#sessionInfo\s+(\S+)\s+(.*)', content):
        session_info[m.group(1)] = m.group(2).strip().strip('"')

    results = []
    for m in re.finditer(
        r"#beginTestCaseResult\s+(\S+)\s*\n(.*?)#endTestCaseResult",
        content, re.DOTALL
    ):
        test_name = m.group(1)
        xml_block = m.group(2)
        sm = re.search(r'StatusCode="(\w+)"', xml_block)
        if sm:
            results.append((test_name, sm.group(1)))
    return results, session_info


def discover_and_extract(results_dir):
    """Discover all QPA files, extracting from archives and decompressing as needed."""
    # Extract tar.gz archives
    for tgz in glob.glob(os.path.join(results_dir, "*.tar.gz")):
        with tarfile.open(tgz, "r:gz") as tar:
            tar.extractall(results_dir, filter='data')

    # Decompress .qpa.gz files
    for qpagz in glob.glob(os.path.join(results_dir, "**/*.qpa.gz"), recursive=True):
        out_path = qpagz[:-3]
        with gzip.open(qpagz, "rb") as f_in:
            with open(out_path, "wb") as f_out:
                f_out.write(f_in.read())

    return sorted(glob.glob(os.path.join(results_dir, "**/*.qpa"), recursive=True))


def load_mustpass(mustpass_dir):
    """Load complete mustpass test set from index + category files."""
    index = os.path.join(mustpass_dir, "vk-default.txt")
    tests = set()
    with open(index) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cat_path = os.path.join(mustpass_dir, line)
            if os.path.isfile(cat_path):
                with open(cat_path) as cf:
                    for tl in cf:
                        tl = tl.strip()
                        if tl:
                            tests.add(tl)
    return tests


def compute_applicable_mustpass(raw_mustpass, ext_test_map, device_exts):
    """Exclude extension-gated tests for unsupported extensions."""
    excluded = set()
    for ext_name, patterns in ext_test_map.items():
        if ext_name not in device_exts:
            for test in raw_mustpass:
                for pattern in patterns:
                    if fnmatch.fnmatch(test, pattern):
                        excluded.add(test)
                        break
    return raw_mustpass - excluded


def parse_waivers(waiver_file, device_id, cts_version):
    """Parse waiver XML. Returns (applicable_patterns, expired_patterns)."""
    tree = ET.parse(waiver_file)
    applicable = []
    expired = []

    for waiver in tree.getroot().findall("waiver"):
        # Check device scope
        device_ids = []
        device_list = waiver.find("device_list")
        if device_list is not None:
            for d_elem in device_list.findall("d"):
                if d_elem.text:
                    device_ids.append(d_elem.text.strip())
        if device_id not in device_ids:
            continue

        # Check version validity
        valid_until = waiver.get("validUntil")
        if valid_until and parse_version(valid_until) < parse_version(cts_version):
            for t_elem in waiver.findall("t"):
                if t_elem.text:
                    expired.append(t_elem.text.strip())
            continue

        # Valid waiver for this device
        for t_elem in waiver.findall("t"):
            if t_elem.text:
                applicable.append(t_elem.text.strip())

    return applicable, expired


def validate_statement(submission_dir):
    """Validate STATEMENT file. Returns (is_valid, error_list)."""
    required = ["CONFORM_VERSION", "PRODUCT", "CPU", "OS"]
    files = [f for f in os.listdir(submission_dir) if f.startswith("STATEMENT")]
    if not files:
        return False, ["No STATEMENT file found"]

    found = set()
    path = os.path.join(submission_dir, files[0])
    with open(path) as f:
        for line in f:
            line = line.strip()
            if ":" in line:
                field = line.split(":")[0].strip()
                found.add(field)

    errors = [f"Missing required field: {r}" for r in required if r not in found]
    return len(errors) == 0, errors


def main():
    # 1. Load raw mustpass
    raw_mustpass = load_mustpass(f"{DATA_DIR}/mustpass")

    # 2. Load device info and extensions
    with open(f"{DATA_DIR}/device-info.json") as f:
        device_info = json.load(f)
    device_id = device_info["deviceId"]

    with open(f"{DATA_DIR}/device-extensions.json") as f:
        device_ext_data = json.load(f)
    device_extensions = set(device_ext_data["supported_extensions"])

    with open(f"{DATA_DIR}/extension-test-map.json") as f:
        extension_test_map = json.load(f)

    # 3. Compute applicable mustpass (exclude extension-gated for unsupported exts)
    applicable_mustpass = compute_applicable_mustpass(
        raw_mustpass, extension_test_map, device_extensions)

    # 4. Discover and parse all QPA result files
    qpa_files = discover_and_extract(f"{DATA_DIR}/results")

    per_fraction = {}       # filepath -> {test: status} after intra-fraction resolution
    fraction_sessions = {}  # filepath -> session_info dict
    duplicate_tests = set()

    for qpa_file in qpa_files:
        entries, session_info = parse_qpa_file(qpa_file)
        fraction_sessions[qpa_file] = session_info

        # Intra-fraction duplicate resolution: last occurrence wins
        seen = {}
        for name, status in entries:
            if name in seen:
                duplicate_tests.add(name)
            seen[name] = status
        per_fraction[qpa_file] = seen

    # 5. Extract CTS version from session info
    cts_version = None
    for si in fraction_sessions.values():
        if "releaseName" in si:
            cts_version = si["releaseName"]
            break

    # 6. Cross-fraction merge with severity-based conflict resolution
    all_results = {}
    cross_fraction_conflicts = set()

    for frac_resolved in per_fraction.values():
        for name, status in frac_resolved.items():
            if name in all_results:
                existing = all_results[name]
                if existing != status:
                    cross_fraction_conflicts.add(name)
                    if severity_of(status) > severity_of(existing):
                        all_results[name] = status
            else:
                all_results[name] = status

    # 7. Parse waivers with device filtering and version checking
    waiver_patterns, expired_patterns = parse_waivers(
        f"{DATA_DIR}/waivers/waivers.xml", device_id, cts_version)

    # 8. Load fraction-mandatory tests
    with open(f"{DATA_DIR}/fraction-mandatory.txt") as f:
        mandatory = {l.strip() for l in f if l.strip()}

    # 9. Check fraction mandatory completeness
    frac_mandatory_ok = True
    for frac_resolved in per_fraction.values():
        if not mandatory.issubset(set(frac_resolved.keys())):
            frac_mandatory_ok = False
            break

    # 10. Missing tests (from applicable mustpass only)
    tests_with_results = set(all_results.keys())
    missing = applicable_mustpass - tests_with_results

    # 11. Raw status counts (after all resolution, before waivers)
    raw_counts = defaultdict(int)
    for status in all_results.values():
        raw_counts[status] += 1

    # 12. Apply waivers (only valid, non-expired, device-matching)
    waived = set()
    effective = {}
    for name, status in all_results.items():
        if status == "Fail" and any(fnmatch.fnmatch(name, p) for p in waiver_patterns):
            waived.add(name)
            effective[name] = "Waiver"
        else:
            effective[name] = status

    # 13. Effective status counts
    eff_counts = defaultdict(int)
    for status in effective.values():
        eff_counts[status] += 1

    # 14. Conformance violations
    violations = sorted(n for n, s in effective.items() if s not in ALLOWED_STATUSES)

    # 15. Validate statement
    stmt_valid, stmt_errors = validate_statement(f"{DATA_DIR}/submission")

    # 16. Overall conformance
    overall = (
        len(violations) == 0
        and len(missing) == 0
        and stmt_valid
        and frac_mandatory_ok
    )

    report = {
        "raw_mustpass_total": len(raw_mustpass),
        "applicable_mustpass_total": len(applicable_mustpass),
        "tests_with_results": len(tests_with_results),
        "tests_missing_count": len(missing),
        "tests_missing": sorted(missing),
        "raw_status_counts": dict(raw_counts),
        "waived_tests_count": len(waived),
        "waived_tests": sorted(waived),
        "expired_waivers_count": len(expired_patterns),
        "expired_waivers": sorted(expired_patterns),
        "effective_status_counts": dict(eff_counts),
        "conformance_violations_count": len(violations),
        "conformance_violations": violations,
        "duplicate_results_count": len(duplicate_tests),
        "duplicate_results": sorted(duplicate_tests),
        "cross_fraction_conflicts_count": len(cross_fraction_conflicts),
        "cross_fraction_conflicts": sorted(cross_fraction_conflicts),
        "fraction_count": len(qpa_files),
        "fraction_mandatory_complete": frac_mandatory_ok,
        "statement_valid": stmt_valid,
        "statement_errors": stmt_errors,
        "overall_conformant": overall,
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to /app/report.json")
    print(f"Overall conformant: {overall}")


if __name__ == "__main__":
    main()
