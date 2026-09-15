
import subprocess
import os
import tempfile

import pytest

INTERP = "/app/coolinterp"
PROGRAMS_DIR = "/app/programs"


# ============================================================
# Structural tests — verify Flex/GCC/Make toolchain usage
# ============================================================

def test_cool_l_exists():
    """Flex lexer specification must exist."""
    assert os.path.isfile("/app/cool.l"), "Missing /app/cool.l (Flex lexer spec)"


def test_makefile_exists():
    """Makefile must exist."""
    assert os.path.isfile("/app/Makefile"), "Missing /app/Makefile"


def test_tokenizer_is_elf_binary():
    """Tokenizer must be a compiled ELF binary, not a script."""
    path = "/app/tokenizer"
    assert os.path.isfile(path), "Missing /app/tokenizer"
    with open(path, "rb") as f:
        magic = f.read(4)
    assert magic == b"\x7fELF", (
        "tokenizer must be a compiled ELF binary (built from Flex via gcc), "
        f"got magic bytes {magic!r}"
    )


def test_coolinterp_executable():
    """Interpreter entry point must exist and be executable."""
    assert os.path.isfile(INTERP), f"Missing {INTERP}"
    assert os.access(INTERP, os.X_OK), f"{INTERP} is not executable"


# ============================================================
# Static program tests — expected outputs encoded here
# ============================================================

_STATIC_EXPECTED = {
    "hello": "Hello, World!\ntab:\there\nbackslash:\\\nquote:\"hi\"\n",
    "fibonacci": "0 1 1 2 3 5 8 13 21 34\n",
    "dispatch": "...\nWoof\nMeow\nI am Derived\nI am Base\n1 11 22\n",
    "case_match": "Matched A: A\nMatched B: B\nMatched C: C\nMatched B: D\n",
    "selftype": "test: 3\n42\nIs Special\n",
    "scoping": "0 '' false void\n100\n1\n11\n1\n100\n",
    "strings": "13\nHello\nWorld\nHello, World! Cool!\nabcdefghi\n0\n",
    "list": "5 4 3 2 1\nSum: 15\nReversed: 1 2 3 4 5\nLength: 5\n",
}


@pytest.mark.parametrize("name", sorted(_STATIC_EXPECTED.keys()))
def test_static_program(name):
    program = os.path.join(PROGRAMS_DIR, name + ".cl")
    assert os.path.isfile(program), f"Program file {program} not found"

    result = subprocess.run(
        [INTERP, program],
        capture_output=True,
        text=True,
        timeout=30,
    )
    expected = _STATIC_EXPECTED[name]

    assert result.returncode == 0, (
        f"Program {name} exited with code {result.returncode}\n"
        f"stderr:\n{result.stderr}"
    )
    assert result.stdout == expected, (
        f"Output mismatch for {name}.\n"
        f"Expected ({len(expected)} chars):\n{expected!r}\n"
        f"Got ({len(result.stdout)} chars):\n{result.stdout!r}"
    )


# ============================================================
# Dynamic tests — programs generated at runtime
# ============================================================

def _run_cool_source(source):
    """Write Cool source to temp file, run interpreter, return (rc, stdout, stderr)."""
    with tempfile.NamedTemporaryFile(
        suffix=".cl", mode="w", delete=False, dir="/tmp"
    ) as f:
        f.write(source)
        path = f.name
    try:
        result = subprocess.run(
            [INTERP, path], capture_output=True, text=True, timeout=30
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        os.unlink(path)


def _rand_int(entropy, label, lo, hi):
    """Derive a deterministic-per-run random int from entropy bytes."""
    import hashlib

    h = hashlib.sha256(entropy + label.encode()).digest()
    val = int.from_bytes(h[:4], "big")
    return lo + (val % (hi - lo + 1))


def test_dynamic_arithmetic():
    """Arithmetic with runtime-random values — cannot be pre-computed."""
    entropy = os.urandom(32)
    a = _rand_int(entropy, "a", 10, 99)
    b = _rand_int(entropy, "b", 10, 99)
    c = _rand_int(entropy, "c", 2, 9)

    source = (
        "class Main inherits IO {\n"
        "    main() : Object {\n"
        "        {\n"
        f'            out_int({a} + {b});\n'
        '            out_string("\\n");\n'
        f'            out_int({a} * {b});\n'
        '            out_string("\\n");\n'
        f"            out_int({a * b} / {c});\n"
        '            out_string("\\n");\n'
        f"            out_int({a} - {b});\n"
        '            out_string("\\n");\n'
        "        }\n"
        "    };\n"
        "};\n"
    )

    div_result = a * b // c
    if (a * b < 0) != (c < 0) and a * b % c != 0:
        div_result = -(abs(a * b) // abs(c))
    expected = f"{a + b}\n{a * b}\n{div_result}\n{a - b}\n"

    rc, stdout, stderr = _run_cool_source(source)
    assert rc == 0, f"Exit {rc}\nstderr: {stderr}"
    assert stdout == expected, f"Expected: {expected!r}\nGot: {stdout!r}"


def test_dynamic_let_scoping():
    """Let binding and shadowing with runtime values."""
    entropy = os.urandom(32)
    x = _rand_int(entropy, "x", 1, 200)
    y = _rand_int(entropy, "y", 1, 200)

    source = (
        "class Main inherits IO {\n"
        "    main() : Object {\n"
        f"        let a : Int <- {x} in\n"
        "        {\n"
        '            out_int(a);\n'
        '            out_string("\\n");\n'
        f"            let a : Int <- a + {y} in\n"
        "            {\n"
        '                out_int(a);\n'
        '                out_string("\\n");\n'
        "            };\n"
        '            out_int(a);\n'
        '            out_string("\\n");\n'
        "        }\n"
        "    };\n"
        "};\n"
    )

    expected = f"{x}\n{x + y}\n{x}\n"

    rc, stdout, stderr = _run_cool_source(source)
    assert rc == 0, f"Exit {rc}\nstderr: {stderr}"
    assert stdout == expected, f"Expected: {expected!r}\nGot: {stdout!r}"


def test_dynamic_dispatch():
    """Dynamic and static dispatch with runtime values."""
    entropy = os.urandom(32)
    val = _rand_int(entropy, "val", 100, 999)

    source = (
        "class Base inherits IO {\n"
        f"    x : Int <- {val};\n"
        "    getX() : Int { x };\n"
        '    tag() : String { "base" };\n'
        "};\n"
        "class Child inherits Base {\n"
        '    tag() : String { "child" };\n'
        "};\n"
        "class Main inherits IO {\n"
        "    main() : Object {\n"
        "        let c : Child <- new Child in\n"
        "        {\n"
        "            out_string(c.tag());\n"
        '            out_string("\\n");\n'
        "            out_int(c.getX());\n"
        '            out_string("\\n");\n'
        "            out_string(c@Base.tag());\n"
        '            out_string("\\n");\n'
        "        }\n"
        "    };\n"
        "};\n"
    )

    expected = f"child\n{val}\nbase\n"

    rc, stdout, stderr = _run_cool_source(source)
    assert rc == 0, f"Exit {rc}\nstderr: {stderr}"
    assert stdout == expected, f"Expected: {expected!r}\nGot: {stdout!r}"
