"""
Tests for BagIt forensic recovery: validator conformance, repaired archives,
and forensic report accuracy.

Verifies:
1. The validator at /app/bagit-validate correctly classifies every bag
   in the LOC conformance suite.
2. Each repaired archive in /app/repaired-archives/ is a valid v1.0 bag
   with correct serialization, checksums, and no remaining violations.
3. The forensic report at /app/forensic-report.json accurately identifies
   the violation categories in each damaged archive.

"""

import hashlib
import json
import os
import re
import subprocess
import tarfile

import pytest

SUITE_DIR = "/app/conformance-suite"
VALIDATOR = "/app/bagit-validate"
REPAIRED_DIR = "/app/repaired-archives"
FORENSIC_REPORT = "/app/forensic-report.json"

FILESYSTEM_DEPENDENT_WARNINGS = {
    "duplicate-file-with-different-case",
    "same-filename-listed-twice-with-different-normalization",
    "special-system-files",
}

REPAIRED_BAG_NAMES = [
    "research-dataset",
    "photo-collection",
    "audio-archive",
    "manuscript-collection",
]

FORENSIC_CATEGORIES = {
    "checksum",
    "completeness",
    "encoding",
    "structure",
    "path-security",
    "serialization",
    "metadata",
}

# Ground-truth: each damaged bag must report at least one of these categories
EXPECTED_FORENSIC = {
    "research-dataset": {"encoding", "checksum", "metadata"},
    "photo-collection": {"serialization", "completeness"},
    "audio-archive": {"path-security", "checksum"},
    "manuscript-collection": {"completeness", "structure"},
}


# ===================================================================
# Helpers
# ===================================================================


def discover_bags():
    """Discover all conformance suite test bags."""
    cases = []
    if not os.path.isdir(SUITE_DIR):
        return cases
    for vdir in sorted(os.listdir(SUITE_DIR)):
        vpath = os.path.join(SUITE_DIR, vdir)
        if not os.path.isdir(vpath) or not vdir.startswith("v"):
            continue
        for cat in sorted(os.listdir(vpath)):
            cpath = os.path.join(vpath, cat)
            if not os.path.isdir(cpath) or cat == "windows-only":
                continue
            for bname in sorted(os.listdir(cpath)):
                bpath = os.path.join(cpath, bname)
                if os.path.isdir(bpath):
                    cases.append((vdir, cat, bname, bpath))
    return cases


BAGS = discover_bags()


def extract_to(bag_name, tmp_path):
    """Extract a repaired archive into tmp_path. Returns bag directory."""
    archive = os.path.join(REPAIRED_DIR, f"{bag_name}.tar.gz")
    if not os.path.isfile(archive):
        pytest.skip(f"Missing: {archive}")
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(str(tmp_path))
    entries = os.listdir(str(tmp_path))
    dirs = [e for e in entries if os.path.isdir(os.path.join(str(tmp_path), e))]
    if len(dirs) != 1:
        pytest.fail(
            f"Expected 1 top-level dir in {bag_name}.tar.gz, got {entries}"
        )
    return os.path.join(str(tmp_path), dirs[0])


# ===================================================================
# Section 1: Validator existence and conformance suite presence
# ===================================================================


def test_validator_exists():
    """The validator executable must exist and be executable."""
    assert os.path.isfile(VALIDATOR), f"Validator not found at {VALIDATOR}"
    assert os.access(VALIDATOR, os.X_OK), f"Validator at {VALIDATOR} is not executable"


def test_conformance_suite_exists():
    """The conformance suite must be present with required versions."""
    assert os.path.isdir(SUITE_DIR), f"Conformance suite not found at {SUITE_DIR}"
    assert os.path.isdir(os.path.join(SUITE_DIR, "v0.97")), "Missing v0.97"
    assert os.path.isdir(os.path.join(SUITE_DIR, "v1.0")), "Missing v1.0"


# ===================================================================
# Section 2: Valid bags MUST exit 0
# ===================================================================


def get_valid_bags():
    return [(v, c, n, p) for v, c, n, p in BAGS if c == "valid"]


@pytest.mark.parametrize(
    "version,category,bag_name,bag_path",
    get_valid_bags(),
    ids=[f"{v}/{c}/{n}" for v, c, n, _ in get_valid_bags()],
)
def test_valid_bag(version, category, bag_name, bag_path):
    """Valid bags MUST be accepted (exit 0)."""
    result = subprocess.run([VALIDATOR, bag_path], capture_output=True, timeout=30)
    assert result.returncode == 0, (
        f"Valid bag {version}/{category}/{bag_name} got exit {result.returncode}\n"
        f"stderr: {result.stderr.decode('utf-8', errors='replace')[:2000]}"
    )


# ===================================================================
# Section 3: Invalid bags MUST exit non-zero
# ===================================================================


def get_invalid_bags():
    return [(v, c, n, p) for v, c, n, p in BAGS if c in ("invalid", "linux-only")]


@pytest.mark.parametrize(
    "version,category,bag_name,bag_path",
    get_invalid_bags(),
    ids=[f"{v}/{c}/{n}" for v, c, n, _ in get_invalid_bags()],
)
def test_invalid_bag(version, category, bag_name, bag_path):
    """Invalid and linux-only bags MUST be rejected (exit non-zero)."""
    result = subprocess.run([VALIDATOR, bag_path], capture_output=True, timeout=30)
    assert result.returncode != 0, (
        f"Invalid bag {version}/{category}/{bag_name} got exit 0\n"
        f"stdout: {result.stdout.decode('utf-8', errors='replace')[:2000]}"
    )


# ===================================================================
# Section 4: Warning bags (platform-independent) should exit 0
# ===================================================================


def get_warning_bags_strict():
    return [
        (v, c, n, p)
        for v, c, n, p in BAGS
        if c == "warning" and n not in FILESYSTEM_DEPENDENT_WARNINGS
    ]


@pytest.mark.parametrize(
    "version,category,bag_name,bag_path",
    get_warning_bags_strict(),
    ids=[f"{v}/{c}/{n}" for v, c, n, _ in get_warning_bags_strict()],
)
def test_warning_bag_accepted(version, category, bag_name, bag_path):
    """Platform-independent warning bags should be accepted (exit 0)."""
    result = subprocess.run([VALIDATOR, bag_path], capture_output=True, timeout=30)
    assert result.returncode == 0, (
        f"Warning bag {version}/{category}/{bag_name} got exit {result.returncode}\n"
        f"stderr: {result.stderr.decode('utf-8', errors='replace')[:2000]}"
    )


# ===================================================================
# Section 5: Repaired archives — existence and serialization
# ===================================================================


@pytest.mark.parametrize("bag_name", REPAIRED_BAG_NAMES)
def test_repaired_archive_exists(bag_name):
    """Each repaired archive must exist."""
    path = os.path.join(REPAIRED_DIR, f"{bag_name}.tar.gz")
    assert os.path.isfile(path), f"Missing: {path}"


@pytest.mark.parametrize("bag_name", REPAIRED_BAG_NAMES)
def test_repaired_serialization_structure(bag_name):
    """Archive must have single top-level directory matching bag name."""
    archive = os.path.join(REPAIRED_DIR, f"{bag_name}.tar.gz")
    if not os.path.isfile(archive):
        pytest.skip("Archive missing")

    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getnames()

    top_level = set()
    for m in members:
        top_level.add(m.split("/")[0])

    assert len(top_level) == 1, (
        f"Expected 1 top-level entry, got {sorted(top_level)}"
    )
    assert bag_name in top_level, (
        f"Top-level should be '{bag_name}', got {sorted(top_level)}"
    )


# ===================================================================
# Section 6: Repaired bags — BagIt v1.0 compliance
# ===================================================================


@pytest.mark.parametrize("bag_name", REPAIRED_BAG_NAMES)
def test_repaired_bagit_txt_format(bag_name, tmp_path):
    """bagit.txt must have no BOM, version 1.0, encoding UTF-8."""
    bag_dir = extract_to(bag_name, tmp_path)
    bagit_path = os.path.join(bag_dir, "bagit.txt")
    assert os.path.isfile(bagit_path), "Missing bagit.txt"

    with open(bagit_path, "rb") as f:
        raw = f.read()

    assert raw[:3] != b"\xef\xbb\xbf", "bagit.txt still contains BOM"

    text = raw.decode("utf-8")
    lines = [l.rstrip("\r\n") for l in text.split("\n") if l.strip()]
    assert len(lines) >= 2, f"bagit.txt needs >= 2 lines, got {len(lines)}"
    assert lines[0] == "BagIt-Version: 1.0", (
        f"Expected 'BagIt-Version: 1.0', got '{lines[0]}'"
    )
    assert lines[1].startswith("Tag-File-Character-Encoding:"), (
        f"Missing encoding declaration, got '{lines[1]}'"
    )
    enc = lines[1].split(":", 1)[1].strip().upper().replace("-", "")
    assert enc == "UTF8", f"Encoding should be UTF-8, got '{lines[1]}'"


@pytest.mark.parametrize("bag_name", REPAIRED_BAG_NAMES)
def test_repaired_no_path_traversal(bag_name, tmp_path):
    """Manifests and fetch.txt must have no path traversal entries."""
    bag_dir = extract_to(bag_name, tmp_path)

    for entry in os.listdir(bag_dir):
        is_manifest = (
            (entry.startswith("manifest-") or entry.startswith("tagmanifest-"))
            and entry.endswith(".txt")
        )
        is_fetch = entry == "fetch.txt"
        if not (is_manifest or is_fetch):
            continue

        path = os.path.join(bag_dir, entry)
        with open(path) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                if is_manifest:
                    m = re.match(r"^[0-9a-fA-F]+\s+(.+)$", line)
                    fp = m.group(1) if m else line
                else:
                    parts = line.split(None, 2)
                    fp = parts[2] if len(parts) >= 3 else ""

                split = fp.replace("\\", "/").split("/")
                assert ".." not in split, (
                    f"Path traversal in {entry}:{line_num}: {fp}"
                )
                assert not fp.startswith("/"), (
                    f"Absolute path in {entry}:{line_num}: {fp}"
                )
                assert not fp.startswith("~"), (
                    f"Home shortcut in {entry}:{line_num}: {fp}"
                )


@pytest.mark.parametrize("bag_name", REPAIRED_BAG_NAMES)
def test_repaired_checksums_correct(bag_name, tmp_path):
    """All checksums in all manifests must match actual file content."""
    bag_dir = extract_to(bag_name, tmp_path)
    errors = []

    for entry in os.listdir(bag_dir):
        m = re.match(r"^(?:tag)?manifest-([a-zA-Z0-9]+)\.txt$", entry)
        if not m:
            continue
        alg = m.group(1).lower()

        manifest_path = os.path.join(bag_dir, entry)
        with open(manifest_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                lm = re.match(r"^([0-9a-fA-F]+)\s+(.+)$", line)
                if not lm:
                    continue
                expected = lm.group(1).lower()
                filepath = lm.group(2)
                full_path = os.path.join(bag_dir, filepath)
                if not os.path.isfile(full_path):
                    errors.append(f"{entry}: file not found: {filepath}")
                    continue

                h = hashlib.new(alg)
                with open(full_path, "rb") as fh:
                    h.update(fh.read())
                actual = h.hexdigest()
                if actual != expected:
                    errors.append(
                        f"{entry}: {filepath}: "
                        f"expected {expected[:20]}… got {actual[:20]}…"
                    )

    assert not errors, "Checksum errors:\n" + "\n".join(errors)


@pytest.mark.parametrize("bag_name", REPAIRED_BAG_NAMES)
def test_repaired_all_manifests_list_all_files(bag_name, tmp_path):
    """v1.0: every payload file must appear in every payload manifest."""
    bag_dir = extract_to(bag_name, tmp_path)

    data_dir = os.path.join(bag_dir, "data")
    payload_files = set()
    if os.path.isdir(data_dir):
        for root, _, files in os.walk(data_dir):
            for fn in files:
                rel = os.path.relpath(os.path.join(root, fn), bag_dir)
                payload_files.add(rel)

    if not payload_files:
        return

    for entry in os.listdir(bag_dir):
        if not (entry.startswith("manifest-") and entry.endswith(".txt")):
            continue

        listed = set()
        with open(os.path.join(bag_dir, entry)) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"^[0-9a-fA-F]+\s+(.+)$", line)
                if m:
                    listed.add(m.group(1))

        missing = payload_files - listed
        assert not missing, f"{entry} missing payload files: {sorted(missing)}"


@pytest.mark.parametrize("bag_name", REPAIRED_BAG_NAMES)
def test_repaired_no_duplicate_entries(bag_name, tmp_path):
    """Manifests must not have duplicate filename entries."""
    bag_dir = extract_to(bag_name, tmp_path)

    for entry in os.listdir(bag_dir):
        is_mf = (
            (entry.startswith("manifest-") or entry.startswith("tagmanifest-"))
            and entry.endswith(".txt")
        )
        if not is_mf:
            continue

        seen = set()
        with open(os.path.join(bag_dir, entry)) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"^[0-9a-fA-F]+\s+(.+)$", line)
                if m:
                    fp = m.group(1)
                    assert fp not in seen, f"Duplicate in {entry}: {fp}"
                    seen.add(fp)


@pytest.mark.parametrize("bag_name", REPAIRED_BAG_NAMES)
def test_repaired_no_metadata_violations(bag_name, tmp_path):
    """bag-info.txt must not have whitespace before colon in labels."""
    bag_dir = extract_to(bag_name, tmp_path)
    baginfo = os.path.join(bag_dir, "bag-info.txt")
    if not os.path.isfile(baginfo):
        return

    with open(baginfo) as f:
        for line_num, line in enumerate(f, 1):
            if line.startswith(" ") or line.startswith("\t"):
                continue
            m = re.match(r"^(\S+)\s+:", line)
            if m:
                pytest.fail(
                    f"bag-info.txt:{line_num}: whitespace before colon: "
                    f"{line.rstrip()}"
                )


@pytest.mark.parametrize("bag_name", REPAIRED_BAG_NAMES)
def test_repaired_validator_passes(bag_name, tmp_path):
    """The validator must exit 0 on every repaired bag."""
    bag_dir = extract_to(bag_name, tmp_path)
    result = subprocess.run([VALIDATOR, bag_dir], capture_output=True, timeout=30)
    assert result.returncode == 0, (
        f"Validator rejected repaired {bag_name}: exit {result.returncode}\n"
        f"stderr: {result.stderr.decode('utf-8', errors='replace')[:2000]}"
    )


# ===================================================================
# Section 7: Forensic report — structure and accuracy
# ===================================================================


def test_forensic_report_exists():
    """The forensic report must exist."""
    assert os.path.isfile(FORENSIC_REPORT), f"Missing: {FORENSIC_REPORT}"


def test_forensic_report_valid_json():
    """The forensic report must be valid JSON."""
    with open(FORENSIC_REPORT) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Report must be a JSON object"


def test_forensic_report_covers_all_bags():
    """Every damaged archive must appear in the forensic report."""
    with open(FORENSIC_REPORT) as f:
        data = json.load(f)
    for name in REPAIRED_BAG_NAMES:
        assert name in data, f"Missing entry for '{name}'"


def test_forensic_report_valid_categories():
    """Every category in the report must be from the defined taxonomy."""
    with open(FORENSIC_REPORT) as f:
        data = json.load(f)
    for name, cats in data.items():
        assert isinstance(cats, list), (
            f"{name}: categories must be a list, got {type(cats).__name__}"
        )
        assert len(cats) > 0, f"{name}: must have at least one category"
        for cat in cats:
            assert cat in FORENSIC_CATEGORIES, (
                f"{name}: unknown category '{cat}'. "
                f"Valid: {sorted(FORENSIC_CATEGORIES)}"
            )


def test_forensic_report_accuracy():
    """Each bag's categories must include at least one expected category."""
    with open(FORENSIC_REPORT) as f:
        data = json.load(f)

    failures = []
    for name, expected in EXPECTED_FORENSIC.items():
        if name not in data:
            failures.append(f"  {name}: missing from report")
            continue
        reported = set(data[name])
        if not reported & expected:
            failures.append(
                f"  {name}: reported {sorted(reported)}, "
                f"expected at least one of {sorted(expected)}"
            )

    assert not failures, (
        "Forensic report inaccuracies:\n" + "\n".join(failures)
    )
