
import subprocess
import tempfile
import os


def _compile_main():
    """Compile the test driver against /app sources."""
    os.makedirs("/tmp/ghc_out", exist_ok=True)
    return subprocess.run(
        [
            "ghc", "-i/app",
            "-odir", "/tmp/ghc_out",
            "-hidir", "/tmp/ghc_out",
            "-o", "/tmp/test_record",
            "/tests/TestDriver.hs",
        ],
        capture_output=True, text=True, timeout=180,
    )


def test_compilation():
    """The Haskell code must compile without errors."""
    result = _compile_main()
    assert result.returncode == 0, (
        f"Compilation failed:\n{result.stderr}"
    )


def test_runtime():
    """All runtime assertions in TestDriver.hs must pass."""
    comp = _compile_main()
    assert comp.returncode == 0, f"Compilation failed:\n{comp.stderr}"

    run = subprocess.run(
        ["/tmp/test_record"],
        capture_output=True, text=True, timeout=30,
    )
    assert run.returncode == 0, (
        f"Runtime error (exit {run.returncode}):\n{run.stderr}\n{run.stdout}"
    )
    assert "ALL TESTS PASSED" in run.stdout, (
        f"Tests did not all pass:\n{run.stdout}"
    )


def test_duplicate_insert_rejected():
    """Inserting a duplicate key must fail at compile time."""
    code = (
        '{-# LANGUAGE DataKinds #-}\n'
        '{-# LANGUAGE OverloadedLabels #-}\n'
        'module DupInsert where\n'
        'import Data.Functor.Identity\n'
        'import ExtensibleRecord\n'
        'bad :: OpenProduct Identity \'[ \'("x", Bool), \'("x", Int) ]\n'
        'bad = insert #x (Identity True) (insert #x (Identity (1 :: Int)) nil)\n'
    )
    fd, tmp_path = tempfile.mkstemp(suffix=".hs", dir="/tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(code)
        result = subprocess.run(
            [
                "ghc", "-i/app", "-c", tmp_path,
                "-odir", "/tmp/ghc_dup",
                "-hidir", "/tmp/ghc_dup",
                "-no-keep-hi-files", "-no-keep-o-files",
            ],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode != 0, (
            "Duplicate insert should be REJECTED at compile time, "
            "but compilation succeeded."
        )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_overlapping_merge_rejected():
    """Merging products with overlapping keys must fail at compile time."""
    code = (
        '{-# LANGUAGE DataKinds #-}\n'
        '{-# LANGUAGE OverloadedLabels #-}\n'
        'module OverlapMerge where\n'
        'import Data.Functor.Identity\n'
        'import ExtensibleRecord\n'
        'bad = merge\n'
        '    (insert #x (Identity (1 :: Int)) nil)\n'
        '    (insert #x (Identity True) nil)\n'
    )
    fd, tmp_path = tempfile.mkstemp(suffix=".hs", dir="/tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(code)
        result = subprocess.run(
            [
                "ghc", "-i/app", "-c", tmp_path,
                "-odir", "/tmp/ghc_ovl",
                "-hidir", "/tmp/ghc_ovl",
                "-no-keep-hi-files", "-no-keep-o-files",
            ],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode != 0, (
            "Overlapping merge should be REJECTED at compile time, "
            "but compilation succeeded."
        )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
