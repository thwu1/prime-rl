
import os
import subprocess
import zlib
import base64

# Expected answers encoded to discourage casual reading
_ENCODED = "eJxNkMGOxDAIQ+/8JVXQCCXQKg2HydcvhGw7Nw7YfvZ1NhODQRc3Vhh4NPwgKN3cC0FlIS2k8MFeTA0OrGfDbgpiHYefBV3GnaRRpxT65dpCjaefDNUUD5N843+v+TzzzheeqXKS1GhBGGdHDcilu+2LcC1qsRnhi5F1qZZPOHp+pskG4WiR9aJH0JdwsIy6olT6rnq/dPLYPm3Wu7j2R/FuE1zPJtEqshfm9vjSS6p7kOVY8I31Ts/IMcTGrxk9EW5rVnegoxweODLwDyIlto4="


def _decode_answers():
    raw = base64.b64decode(_ENCODED)
    text = zlib.decompress(raw).decode('utf-8')
    return [line for line in text.strip().split('\n') if line]


EXPECTED = _decode_answers()


# === Output correctness tests ===

def test_output_file_exists():
    assert os.path.isfile('/app/output.txt'), \
        "/app/output.txt not found. The agent must write output to this file."


def test_output_line_count():
    with open('/app/output.txt') as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) == len(EXPECTED), \
        f"Expected {len(EXPECTED)} lines, got {len(lines)}"


def test_all_forms_correct():
    with open('/app/output.txt') as f:
        lines = [l.strip() for l in f if l.strip()]

    errors = []
    for i, (got, want) in enumerate(zip(lines, EXPECTED)):
        if got != want:
            errors.append(f"  Line {i+1}: got '{got}', expected '{want}'")

    assert not errors, \
        f"{len(errors)}/{len(EXPECTED)} forms incorrect:\n" + '\n'.join(errors)


# === HFST transducer validation tests ===

def test_hfst_transducer_exists():
    assert os.path.isfile('/app/kaltiru.hfst'), \
        "kaltiru.hfst not found at /app/kaltiru.hfst"


def test_hfst_transducer_valid():
    """Verify the transducer is a valid HFST binary using hfst-summarize."""
    result = subprocess.run(
        ['hfst-summarize', '/app/kaltiru.hfst'],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"hfst-summarize failed (exit {result.returncode}): {result.stderr}"
    out = result.stdout.lower()
    assert 'state' in out or 'arc' in out or 'transition' in out, \
        "hfst-summarize output does not describe a valid transducer"


def test_hfst_lookup_produces_correct_forms():
    """Verify hfst-lookup with the transducer produces correct surface forms."""
    test_pairs = [
        ('stone.PL', 'kallar'),
        ('river.ACC', 'sulugu'),
        ('lake.PL.GEN', 'gellerin'),
        ('house.LOC', 'dovada'),
        ('field.ABL', 'tablaktan'),
    ]
    input_text = '\n'.join(g for g, _ in test_pairs) + '\n'
    result = subprocess.run(
        ['hfst-lookup', '-q', '/app/kaltiru.hfst'],
        input=input_text, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"hfst-lookup failed (exit {result.returncode}): {result.stderr}"

    for gloss, expected_form in test_pairs:
        assert expected_form in result.stdout, \
            f"hfst-lookup did not produce '{expected_form}' for gloss '{gloss}'. " \
            f"Output was: {result.stdout[:500]}"


# === Build pipeline tests ===

def test_makefile_exists():
    assert os.path.isfile('/app/Makefile'), \
        "Makefile not found at /app/Makefile"


def test_lexc_file_exists():
    assert os.path.isfile('/app/kaltiru.lexc'), \
        "LEXC grammar not found at /app/kaltiru.lexc"


def test_lexc_compiles():
    """Verify the LEXC file compiles with hfst-lexc."""
    result = subprocess.run(
        ['hfst-lexc', '/app/kaltiru.lexc', '-o', '/tmp/test_lexc.hfst'],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"hfst-lexc compilation failed (exit {result.returncode}): {result.stderr}"
    assert os.path.isfile('/tmp/test_lexc.hfst'), \
        "hfst-lexc did not produce output file"
