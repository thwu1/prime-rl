
"""
Tests for Coq soundness audit task.

Verifies:
- Exploit files compile and prove False with no axioms
- Fixed files compile, export correct API, and are not exploitable
"""

import subprocess
import os
import tempfile
import pytest


def coqc(filepath, timeout=120):
    """Compile a Coq file and return the subprocess result."""
    result = subprocess.run(
        ['coqc', filepath],
        capture_output=True, text=True, timeout=timeout
    )
    return result


def write_temp_coq(code):
    """Write a temporary .v file in /tmp and return its path."""
    fd, path = tempfile.mkstemp(suffix='.v', dir='/tmp', prefix='coqtest_')
    with os.fdopen(fd, 'w') as f:
        f.write(code)
    return path


def cleanup_temp(path):
    """Remove a temp .v file and any compiled artifacts."""
    for ext in ['.v', '.vo', '.glob', '.vok', '.vos', '.aux']:
        p = path.replace('.v', ext)
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


# ============================================================
# Exploit tests
# ============================================================

class TestExploitMod:
    def test_compiles(self):
        assert os.path.exists('/app/exploit_mod.v'), "exploit_mod.v not found"
        r = coqc('/app/exploit_mod.v')
        assert r.returncode == 0, f"exploit_mod.v compilation failed:\n{r.stderr}"

    def test_closed(self):
        r = coqc('/app/exploit_mod.v')
        assert r.returncode == 0, f"exploit_mod.v compilation failed:\n{r.stderr}"
        combined = r.stdout + r.stderr
        assert "Closed under the global context" in combined, \
            f"unsound has axiom dependencies:\n{combined}"


class TestExploitRec:
    def test_compiles(self):
        assert os.path.exists('/app/exploit_rec.v'), "exploit_rec.v not found"
        r = coqc('/app/exploit_rec.v')
        assert r.returncode == 0, f"exploit_rec.v compilation failed:\n{r.stderr}"

    def test_closed(self):
        r = coqc('/app/exploit_rec.v')
        assert r.returncode == 0, f"exploit_rec.v compilation failed:\n{r.stderr}"
        combined = r.stdout + r.stderr
        assert "Closed under the global context" in combined, \
            f"unsound has axiom dependencies:\n{combined}"


class TestExploitIter:
    def test_compiles(self):
        assert os.path.exists('/app/exploit_iter.v'), "exploit_iter.v not found"
        r = coqc('/app/exploit_iter.v')
        assert r.returncode == 0, f"exploit_iter.v compilation failed:\n{r.stderr}"

    def test_closed(self):
        r = coqc('/app/exploit_iter.v')
        assert r.returncode == 0, f"exploit_iter.v compilation failed:\n{r.stderr}"
        combined = r.stdout + r.stderr
        assert "Closed under the global context" in combined, \
            f"unsound has axiom dependencies:\n{combined}"


# ============================================================
# Fixed ModLib tests
# ============================================================

class TestFixedMod:
    def test_compiles(self):
        assert os.path.exists('/app/fixed_mod.v'), "fixed_mod.v not found"
        r = coqc('/app/fixed_mod.v')
        assert r.returncode == 0, f"fixed_mod.v compilation failed:\n{r.stderr}"

    def test_api_values(self):
        """a_current=true, b_current=false, a_flipped=false, b_flipped=true"""
        code = '''
Load "/app/fixed_mod".
Lemma chk_a : a_current = true. Proof. reflexivity. Qed.
Lemma chk_b : b_current = false. Proof. reflexivity. Qed.
Lemma chk_af : a_flipped = false. Proof. reflexivity. Qed.
Lemma chk_bf : b_flipped = true. Proof. reflexivity. Qed.
'''
        path = write_temp_coq(code)
        try:
            r = coqc(path)
            assert r.returncode == 0, \
                f"Fixed ModLib API values incorrect:\n{r.stderr}"
        finally:
            cleanup_temp(path)

    def test_sound(self):
        """a_current = b_current must NOT be provable by reflexivity"""
        code = '''
Load "/app/fixed_mod".
Lemma exploit_check : a_current = b_current.
Proof. reflexivity. Qed.
'''
        path = write_temp_coq(code)
        try:
            r = coqc(path)
            assert r.returncode != 0, \
                "Fixed ModLib still allows a_current = b_current by reflexivity!"
        finally:
            cleanup_temp(path)


# ============================================================
# Fixed RecLib tests
# ============================================================

class TestFixedRec:
    def test_compiles(self):
        assert os.path.exists('/app/fixed_rec.v'), "fixed_rec.v not found"
        r = coqc('/app/fixed_rec.v')
        assert r.returncode == 0, f"fixed_rec.v compilation failed:\n{r.stderr}"

    def test_api(self):
        """deep_acc and shallow_run exist with correct types and values"""
        code = '''
Load "/app/fixed_rec".
Check (deep_acc : nat -> nat -> (nat -> nat) -> nat).
Check (shallow_run : nat -> nat).
Lemma chk_shallow : shallow_run 5 = 7.
Proof. reflexivity. Qed.
'''
        path = write_temp_coq(code)
        try:
            r = coqc(path)
            assert r.returncode == 0, \
                f"Fixed RecLib API check failed:\n{r.stderr}"
        finally:
            cleanup_temp(path)

    def test_sound(self):
        """The closure-capture step lemma must NOT hold by reflexivity"""
        code = '''
Load "/app/fixed_rec".
Lemma bad_step : forall d l f,
  deep_acc (S d) l f = deep_acc d (S l) (fun x => deep_acc x 0 f).
Proof. reflexivity. Qed.
'''
        path = write_temp_coq(code)
        try:
            r = coqc(path)
            assert r.returncode != 0, \
                "Fixed RecLib still has the closure-capture vulnerability!"
        finally:
            cleanup_temp(path)


# ============================================================
# Fixed IterLib tests
# ============================================================

class TestFixedIter:
    def test_compiles(self):
        assert os.path.exists('/app/fixed_iter.v'), "fixed_iter.v not found"
        r = coqc('/app/fixed_iter.v')
        assert r.returncode == 0, f"fixed_iter.v compilation failed:\n{r.stderr}"

    def test_api(self):
        """bounded_result exists as a nat and equals 10"""
        code = '''
Load "/app/fixed_iter".
Check (bounded_result : nat).
Lemma chk_result : bounded_result = 10. Proof. reflexivity. Qed.
'''
        path = write_temp_coq(code)
        try:
            r = coqc(path)
            assert r.returncode == 0, \
                f"Fixed IterLib API check failed:\n{r.stderr}"
        finally:
            cleanup_temp(path)

    def test_sound(self):
        """No False-producing definition should exist via safety_check"""
        code = '''
Load "/app/fixed_iter".
Definition exploit_check : False := safety_check 1 I.
'''
        path = write_temp_coq(code)
        try:
            r = coqc(path)
            assert r.returncode != 0, \
                "Fixed IterLib still allows deriving False via safety_check!"
        finally:
            cleanup_temp(path)
