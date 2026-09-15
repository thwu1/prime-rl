"""
Tests for the InChI processing pipeline.

Verifies that the C program at /app builds with CMake and produces correct
InChIKeys in --keys, --sdf, and --dedup modes. Reference InChIKeys are
verified against the IUPAC InChI library (v1.07) and Wikipedia.
"""

import subprocess
import pytest
import os


# --- Reference data ---

# (InChI string, expected InChIKey, molecule_id)
STANDARD_MOLECULES = [
    ("InChI=1S/H2O/h1H2",
     "XLYOFNOQVPJJNP-UHFFFAOYSA-N",
     "water"),
    ("InChI=1S/CH4/h1H4",
     "VNWKTOKETHGBQD-UHFFFAOYSA-N",
     "methane"),
    ("InChI=1S/CH2O/c1-2/h1H2",
     "WSFSSNUMVMOOMR-UHFFFAOYSA-N",
     "formaldehyde"),
    ("InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3",
     "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
     "ethanol"),
    ("InChI=1S/C2H4O2/c1-2(3)4/h1H3,(H,3,4)",
     "QTBSBXVTEAMEQO-UHFFFAOYSA-N",
     "acetic_acid"),
    ("InChI=1S/C10H18O/c1-9(2)7-4-5-10(9,3)8(11)6-7/h7-8,11H,4-6H2,1-3H3"
     "/t7-,8+,10+/m0/s1",
     "DTGKSKDOIYIVQL-QXFUBDJGSA-N",
     "borneol"),
    ("InChI=1S/C17H19NO3/c1-18-7-6-17-10-3-5-13(20)16(17)21-15-12(19)4-2-"
     "9(14(15)17)8-11(10)18/h2-5,10-11,13,16,19-20H,6-8H2,1H3"
     "/t10-,11+,13-,16-,17-/m0/s1",
     "BQJCRHHNABKAKU-KBQPJGBKSA-N",
     "morphine"),
]

NONSTANDARD_MOLECULE = (
    "InChI=1/C2H6O/c1-2-3/h3H,2H2,1H3",
    "LFQSCWFLJHTTHZ-UHFFFAOYNA-N",
    "ethanol_nonstandard",
)

# SDF records: name -> expected InChIKey
SDF_EXPECTED = {
    "water": "XLYOFNOQVPJJNP-UHFFFAOYSA-N",
    "methane": "VNWKTOKETHGBQD-UHFFFAOYSA-N",
    "formaldehyde": "WSFSSNUMVMOOMR-UHFFFAOYSA-N",
    "ethanol": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
    "acetic_acid": "QTBSBXVTEAMEQO-UHFFFAOYSA-N",
    "borneol": "DTGKSKDOIYIVQL-QXFUBDJGSA-N",
    "morphine": "BQJCRHHNABKAKU-KBQPJGBKSA-N",
    "water_duplicate": "XLYOFNOQVPJJNP-UHFFFAOYSA-N",
    "ethanol_duplicate": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
}


@pytest.fixture(scope="session")
def build_binary():
    """Build the inchi_pipeline binary with CMake."""
    build_dir = "/app/build"
    os.makedirs(build_dir, exist_ok=True)

    # Run cmake
    result = subprocess.run(
        ["cmake", ".."],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"CMake configuration failed:\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

    # Run make
    result = subprocess.run(
        ["make"],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    binary = os.path.join(build_dir, "inchi_pipeline")
    assert os.path.isfile(binary), f"Binary not found at {binary}"
    return binary


def run_pipeline(binary, args, stdin_text=None):
    """Run the pipeline with given args and optional stdin."""
    result = subprocess.run(
        [binary] + args,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result


# ===================== --keys mode tests =====================

@pytest.mark.parametrize(
    "inchi,expected_key,mol_id",
    STANDARD_MOLECULES,
    ids=[m[2] for m in STANDARD_MOLECULES],
)
def test_keys_individual(build_binary, inchi, expected_key, mol_id):
    """Test InChIKey generation for individual standard molecules."""
    result = run_pipeline(build_binary, ["--keys"], stdin_text=inchi + "\n")
    assert result.returncode == 0, (
        f"Binary failed for {mol_id}: {result.stderr}"
    )
    actual = result.stdout.strip()
    assert len(actual) == 27, (
        f"InChIKey for {mol_id} must be 27 chars, got {len(actual)}: '{actual}'"
    )
    assert actual == expected_key, (
        f"InChIKey mismatch for {mol_id}:\n"
        f"  expected: {expected_key}\n"
        f"  actual:   {actual}\n"
        f"  diff pos: "
        f"{[i for i in range(min(len(actual), len(expected_key))) if actual[i] != expected_key[i]]}"
    )


def test_keys_nonstandard(build_binary):
    """Test InChIKey generation for a non-standard InChI string."""
    inchi, expected_key, mol_id = NONSTANDARD_MOLECULE
    result = run_pipeline(build_binary, ["--keys"], stdin_text=inchi + "\n")
    assert result.returncode == 0, (
        f"Binary failed for {mol_id}: {result.stderr}"
    )
    actual = result.stdout.strip()
    assert actual == expected_key, (
        f"Non-standard InChIKey mismatch for {mol_id}:\n"
        f"  expected: {expected_key}\n"
        f"  actual:   {actual}\n"
        f"  The flag character (position 17) should be 'N' for non-standard InChI."
    )


def test_keys_batch(build_binary):
    """Test processing all molecules in a single batch via stdin."""
    all_molecules = STANDARD_MOLECULES + [NONSTANDARD_MOLECULE]
    input_text = "\n".join(m[0] for m in all_molecules) + "\n"
    result = run_pipeline(build_binary, ["--keys"], stdin_text=input_text)
    assert result.returncode == 0, f"Batch processing failed: {result.stderr}"

    output_lines = [l for l in result.stdout.strip().split("\n") if l]
    assert len(output_lines) == len(all_molecules), (
        f"Expected {len(all_molecules)} output lines, got {len(output_lines)}"
    )

    for i, (inchi, expected_key, mol_id) in enumerate(all_molecules):
        assert output_lines[i] == expected_key, (
            f"Batch mismatch at line {i} ({mol_id}):\n"
            f"  expected: {expected_key}\n"
            f"  actual:   {output_lines[i]}"
        )


def test_inchikey_format(build_binary):
    """Test that all output conforms to InChIKey format."""
    for inchi, _, mol_id in STANDARD_MOLECULES:
        result = run_pipeline(build_binary, ["--keys"], stdin_text=inchi + "\n")
        key = result.stdout.strip()
        parts = key.split("-")
        assert len(parts) == 3, (
            f"{mol_id}: expected 3 hyphen-separated parts: {key}"
        )
        assert len(parts[0]) == 14, (
            f"{mol_id}: first part must be 14 chars: {parts[0]}"
        )
        assert len(parts[1]) == 10, (
            f"{mol_id}: second part must be 10 chars: {parts[1]}"
        )
        assert len(parts[2]) == 1, (
            f"{mol_id}: third part must be 1 char: {parts[2]}"
        )
        assert all(c.isalpha() and c.isupper() for c in parts[0]), (
            f"{mol_id}: first part must be uppercase letters: {parts[0]}"
        )
        assert parts[1][-2] in ('S', 'N'), (
            f"{mol_id}: flag character must be S or N, got '{parts[1][-2]}'"
        )
        assert parts[1][-1] == 'A', (
            f"{mol_id}: version character must be A, got '{parts[1][-1]}'"
        )


# ===================== --sdf mode tests =====================

def test_sdf_extraction(build_binary):
    """Test that --sdf mode correctly extracts InChI and generates keys."""
    result = run_pipeline(
        build_binary,
        ["--sdf", "/app/data/molecules.sdf"],
    )
    assert result.returncode == 0, (
        f"SDF mode failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    lines = [l for l in result.stdout.strip().split("\n") if l]
    assert len(lines) == 9, (
        f"Expected 9 SDF output lines, got {len(lines)}:\n"
        + "\n".join(lines)
    )

    for line in lines:
        parts = line.split("\t")
        assert len(parts) == 2, f"SDF output line must be tab-separated: {line}"
        key, name = parts
        assert name in SDF_EXPECTED, (
            f"Unexpected molecule name in SDF output: {name}"
        )
        assert key == SDF_EXPECTED[name], (
            f"SDF InChIKey mismatch for {name}:\n"
            f"  expected: {SDF_EXPECTED[name]}\n"
            f"  actual:   {key}"
        )


def test_sdf_record_count(build_binary):
    """Test that SDF parsing extracts all 9 records."""
    result = run_pipeline(
        build_binary,
        ["--sdf", "/app/data/molecules.sdf"],
    )
    assert result.returncode == 0
    lines = [l for l in result.stdout.strip().split("\n") if l]
    names = [l.split("\t")[1] for l in lines]
    assert len(names) == 9, f"Expected 9 records, got {len(names)}"
    assert "water" in names
    assert "morphine" in names
    assert "water_duplicate" in names
    assert "ethanol_duplicate" in names


# ===================== --dedup mode tests =====================

def test_dedup_finds_duplicates(build_binary):
    """Test that --dedup correctly identifies duplicate molecules."""
    result = run_pipeline(
        build_binary,
        ["--dedup", "/app/data/molecules.sdf"],
    )
    assert result.returncode == 0, (
        f"Dedup mode failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    output = result.stdout
    dup_lines = [l for l in output.split("\n") if l.startswith("DUPLICATE:")]
    assert len(dup_lines) == 2, (
        f"Expected exactly 2 DUPLICATE lines, got {len(dup_lines)}:\n"
        + "\n".join(dup_lines)
    )


def test_dedup_water_pair(build_binary):
    """Test that water duplicate pair is detected."""
    result = run_pipeline(
        build_binary,
        ["--dedup", "/app/data/molecules.sdf"],
    )
    output = result.stdout
    assert "water" in output and "water_duplicate" in output, (
        f"Water duplicate pair not found in output:\n{output}"
    )
    assert "XLYOFNOQVPJJNP-UHFFFAOYSA-N" in output, (
        f"Water InChIKey not found in dedup output:\n{output}"
    )


def test_dedup_ethanol_pair(build_binary):
    """Test that ethanol duplicate pair is detected."""
    result = run_pipeline(
        build_binary,
        ["--dedup", "/app/data/molecules.sdf"],
    )
    output = result.stdout
    assert "ethanol" in output and "ethanol_duplicate" in output, (
        f"Ethanol duplicate pair not found in output:\n{output}"
    )
    assert "LFQSCWFLJHTTHZ-UHFFFAOYSA-N" in output, (
        f"Ethanol InChIKey not found in dedup output:\n{output}"
    )


def test_dedup_total_count(build_binary):
    """Test that the dedup summary reports exactly 2 pairs."""
    result = run_pipeline(
        build_binary,
        ["--dedup", "/app/data/molecules.sdf"],
    )
    output = result.stdout
    assert "Total: 2 duplicate pair(s) found." in output, (
        f"Expected 'Total: 2 duplicate pair(s) found.' in output:\n{output}"
    )


# ===================== edge case tests =====================

def test_keys_standard_vs_nonstandard_flag(build_binary):
    """Test that standard and non-standard ethanol differ only in flag."""
    std_inchi = "InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3"
    nonstd_inchi = "InChI=1/C2H6O/c1-2-3/h3H,2H2,1H3"

    r1 = run_pipeline(build_binary, ["--keys"], stdin_text=std_inchi + "\n")
    r2 = run_pipeline(build_binary, ["--keys"], stdin_text=nonstd_inchi + "\n")
    assert r1.returncode == 0 and r2.returncode == 0

    std_key = r1.stdout.strip()
    nonstd_key = r2.stdout.strip()

    # The major hash (first 14 chars) should be identical
    assert std_key[:14] == nonstd_key[:14], (
        f"Major hash should match for standard vs non-standard:\n"
        f"  standard:     {std_key}\n"
        f"  non-standard: {nonstd_key}"
    )

    # The minor hash (chars 15-22) should be identical
    assert std_key[15:23] == nonstd_key[15:23], (
        f"Minor hash should match for standard vs non-standard:\n"
        f"  standard:     {std_key}\n"
        f"  non-standard: {nonstd_key}"
    )

    # The flag character (position 23) should differ: S vs N
    assert std_key[23] == 'S', f"Standard flag should be S, got {std_key[23]}"
    assert nonstd_key[23] == 'N', (
        f"Non-standard flag should be N, got {nonstd_key[23]}"
    )

    # The rest should be identical
    assert std_key[24:] == nonstd_key[24:], (
        f"Version and protonation should match:\n"
        f"  standard:     {std_key}\n"
        f"  non-standard: {nonstd_key}"
    )
