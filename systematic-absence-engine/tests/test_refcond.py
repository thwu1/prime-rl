"""
Tests for the systematic absence engine /app/refcond.py.
Covers all 7 crystal systems with well-known space groups.
"""

import subprocess
import json
import pytest


def run_check(sg, h, k, l):
    """Run the check command and return 'absent' or 'allowed'."""
    result = subprocess.run(
        ["python3", "/app/refcond.py", "check", str(sg), str(h), str(k), str(l)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"refcond.py check {sg} {h} {k} {l} failed "
        f"(exit {result.returncode}): {result.stderr}"
    )
    return result.stdout.strip()


def run_batch(sg, reflections):
    """Run batch-check and return parsed JSON list."""
    stdin_data = "\n".join(f"{h} {k} {l}" for h, k, l in reflections)
    result = subprocess.run(
        ["python3", "/app/refcond.py", "batch-check", str(sg)],
        capture_output=True, text=True, input=stdin_data, timeout=120,
    )
    assert result.returncode == 0, f"batch-check failed: {result.stderr}"
    return json.loads(result.stdout.strip())


def run_identify(crystal_system, observations):
    """Run identify and return parsed JSON dict."""
    stdin_data = "\n".join(f"{h} {k} {l} {s}" for h, k, l, s in observations)
    result = subprocess.run(
        ["python3", "/app/refcond.py", "identify", crystal_system],
        capture_output=True, text=True, input=stdin_data, timeout=180,
    )
    assert result.returncode == 0, f"identify failed: {result.stderr}"
    return json.loads(result.stdout.strip())


# ================================================================
# Triclinic — no systematic absences
# ================================================================
class TestTriclinic:
    def test_p1_all_allowed(self):
        """P1 (1): no systematic absences at all."""
        for h, k, l in [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 2, 3), (5, 7, 11)]:
            assert run_check(1, h, k, l) == "allowed"

    def test_p_bar1_all_allowed(self):
        """P-1 (2): no systematic absences."""
        for h, k, l in [(1, 0, 0), (1, 1, 1), (3, 5, 7)]:
            assert run_check(2, h, k, l) == "allowed"


# ================================================================
# Monoclinic — screw axes and glide planes
# ================================================================
class TestMonoclinic:
    def test_p21_0k0(self):
        """P21 (4): 0k0: k=2n from 21 screw."""
        assert run_check(4, 0, 1, 0) == "absent"
        assert run_check(4, 0, 2, 0) == "allowed"
        assert run_check(4, 0, 3, 0) == "absent"
        assert run_check(4, 0, 4, 0) == "allowed"
        # no h0l condition
        assert run_check(4, 1, 0, 1) == "allowed"
        assert run_check(4, 1, 0, 3) == "allowed"

    def test_pc_h0l(self):
        """Pc (7): h0l: l=2n from c-glide, 00l: l=2n."""
        assert run_check(7, 1, 0, 1) == "absent"
        assert run_check(7, 1, 0, 2) == "allowed"
        assert run_check(7, 2, 0, 3) == "absent"
        assert run_check(7, 3, 0, 4) == "allowed"
        assert run_check(7, 0, 0, 1) == "absent"
        assert run_check(7, 0, 0, 2) == "allowed"
        # no 0k0 condition
        assert run_check(7, 0, 1, 0) == "allowed"
        assert run_check(7, 0, 3, 0) == "allowed"

    def test_p21c_full(self):
        """P21/c (14): h0l: l=2n, 0k0: k=2n, 00l: l=2n."""
        # h0l
        assert run_check(14, 1, 0, 1) == "absent"
        assert run_check(14, 1, 0, 2) == "allowed"
        assert run_check(14, 3, 0, 5) == "absent"
        assert run_check(14, 2, 0, 4) == "allowed"
        # 0k0
        assert run_check(14, 0, 1, 0) == "absent"
        assert run_check(14, 0, 2, 0) == "allowed"
        assert run_check(14, 0, 5, 0) == "absent"
        assert run_check(14, 0, 6, 0) == "allowed"
        # 00l (subsumed by h0l with h=0)
        assert run_check(14, 0, 0, 1) == "absent"
        assert run_check(14, 0, 0, 2) == "allowed"
        # general: no conditions
        assert run_check(14, 1, 1, 1) == "allowed"
        assert run_check(14, 2, 3, 5) == "allowed"

    def test_c2c_centering_and_glide(self):
        """C2/c (15): hkl: h+k=2n, h0l: l=2n, 0k0: k=2n."""
        # C centering: h+k must be even
        assert run_check(15, 1, 0, 0) == "absent"   # h+k=1
        assert run_check(15, 1, 1, 0) == "allowed"  # h+k=2
        assert run_check(15, 2, 1, 1) == "absent"   # h+k=3
        assert run_check(15, 2, 2, 1) == "allowed"  # h+k=4
        # h0l: l=2n (plus h even from centering)
        assert run_check(15, 2, 0, 1) == "absent"   # l=1 odd
        assert run_check(15, 2, 0, 2) == "allowed"  # l=2 even, h+k=2 even
        # 0k0: k=2n
        assert run_check(15, 0, 1, 0) == "absent"   # k=1
        assert run_check(15, 0, 2, 0) == "allowed"  # k=2


# ================================================================
# Orthorhombic — multiple screw/glide conditions
# ================================================================
class TestOrthorhombic:
    def test_p212121_serial(self):
        """P212121 (19): h00: h=2n, 0k0: k=2n, 00l: l=2n."""
        assert run_check(19, 1, 0, 0) == "absent"
        assert run_check(19, 2, 0, 0) == "allowed"
        assert run_check(19, 3, 0, 0) == "absent"
        assert run_check(19, 0, 1, 0) == "absent"
        assert run_check(19, 0, 2, 0) == "allowed"
        assert run_check(19, 0, 0, 1) == "absent"
        assert run_check(19, 0, 0, 2) == "allowed"
        assert run_check(19, 0, 0, 3) == "absent"
        # general: allowed
        assert run_check(19, 1, 1, 1) == "allowed"
        assert run_check(19, 1, 2, 3) == "allowed"

    def test_pnma_zonal_and_serial(self):
        """Pnma (62): 0kl: k+l=2n, hk0: h=2n, h00: h=2n, 0k0: k=2n, 00l: l=2n."""
        # 0kl: k+l=2n (n-glide)
        assert run_check(62, 0, 1, 0) == "absent"   # k+l=1
        assert run_check(62, 0, 1, 1) == "allowed"  # k+l=2
        assert run_check(62, 0, 2, 1) == "absent"   # k+l=3
        assert run_check(62, 0, 3, 3) == "allowed"  # k+l=6
        # hk0: h=2n (a-glide)
        assert run_check(62, 1, 1, 0) == "absent"   # h=1
        assert run_check(62, 2, 1, 0) == "allowed"  # h=2
        assert run_check(62, 3, 2, 0) == "absent"   # h=3
        assert run_check(62, 4, 3, 0) == "allowed"  # h=4
        # serial
        assert run_check(62, 1, 0, 0) == "absent"   # h=1
        assert run_check(62, 2, 0, 0) == "allowed"  # h=2
        assert run_check(62, 0, 0, 1) == "absent"   # l=1
        assert run_check(62, 0, 0, 2) == "allowed"  # l=2
        # h0l: no condition (m mirror perp to b)
        assert run_check(62, 1, 0, 1) == "allowed"
        assert run_check(62, 3, 0, 5) == "allowed"


# ================================================================
# Tetragonal — I centering, screw axes
# ================================================================
class TestTetragonal:
    def test_i4mmm_centering(self):
        """I4/mmm (139): hkl: h+k+l=2n from I centering."""
        assert run_check(139, 1, 0, 0) == "absent"   # h+k+l=1
        assert run_check(139, 1, 1, 0) == "allowed"  # h+k+l=2
        assert run_check(139, 1, 1, 1) == "absent"   # h+k+l=3
        assert run_check(139, 2, 0, 0) == "allowed"  # h+k+l=2
        assert run_check(139, 2, 1, 0) == "absent"   # h+k+l=3
        assert run_check(139, 3, 2, 1) == "allowed"  # h+k+l=6

    def test_p42_screw(self):
        """P42 (77): 00l: l=2n from 42 screw."""
        assert run_check(77, 0, 0, 1) == "absent"
        assert run_check(77, 0, 0, 2) == "allowed"
        assert run_check(77, 0, 0, 3) == "absent"
        assert run_check(77, 0, 0, 4) == "allowed"
        # general: allowed
        assert run_check(77, 1, 0, 0) == "allowed"
        assert run_check(77, 1, 1, 0) == "allowed"


# ================================================================
# Trigonal — R centering (hexagonal axes, obverse)
# ================================================================
class TestTrigonal:
    def test_r_bar3_centering(self):
        """R-3 (148): -h+k+l=3n in hexagonal obverse setting."""
        assert run_check(148, 1, 0, 0) == "absent"   # -1+0+0=-1
        assert run_check(148, 1, 1, 0) == "allowed"  # -1+1+0=0
        assert run_check(148, 1, 0, 1) == "allowed"  # -1+0+1=0
        assert run_check(148, 0, 0, 1) == "absent"   # 0+0+1=1
        assert run_check(148, 0, 0, 3) == "allowed"  # 0+0+3=3
        assert run_check(148, 1, 2, 0) == "absent"   # -1+2+0=1
        assert run_check(148, 0, 1, 2) == "allowed"  # 0+1+2=3


# ================================================================
# Hexagonal — 63 and 61 screws
# ================================================================
class TestHexagonal:
    def test_p63_screw(self):
        """P63 (173): 00l: l=2n from 63 screw."""
        assert run_check(173, 0, 0, 1) == "absent"
        assert run_check(173, 0, 0, 2) == "allowed"
        assert run_check(173, 0, 0, 3) == "absent"
        assert run_check(173, 0, 0, 4) == "allowed"
        # general: allowed
        assert run_check(173, 1, 0, 0) == "allowed"
        assert run_check(173, 1, 1, 0) == "allowed"

    def test_p61_screw(self):
        """P61 (169): 00l: l=6n from 61 screw."""
        assert run_check(169, 0, 0, 1) == "absent"
        assert run_check(169, 0, 0, 2) == "absent"
        assert run_check(169, 0, 0, 3) == "absent"
        assert run_check(169, 0, 0, 5) == "absent"
        assert run_check(169, 0, 0, 6) == "allowed"
        assert run_check(169, 0, 0, 12) == "allowed"
        # general: allowed
        assert run_check(169, 1, 0, 0) == "allowed"


# ================================================================
# Cubic — F centering, I centering with complex conditions
# ================================================================
class TestCubic:
    def test_fm3m_f_centering(self):
        """Fm-3m (225): hkl all even or all odd (F centering)."""
        assert run_check(225, 1, 1, 1) == "allowed"  # all odd
        assert run_check(225, 2, 0, 0) == "allowed"  # all even
        assert run_check(225, 2, 2, 2) == "allowed"  # all even
        assert run_check(225, 1, 0, 0) == "absent"   # mixed
        assert run_check(225, 1, 1, 0) == "absent"   # mixed
        assert run_check(225, 2, 1, 0) == "absent"   # mixed
        assert run_check(225, 2, 1, 1) == "absent"   # mixed

    def test_ia3d_complex(self):
        """Ia-3d (230): hkl: h+k+l=2n, 0kl: k,l=2n, hhl: 2h+l=4n, h00: h=4n."""
        # I centering
        assert run_check(230, 1, 0, 0) == "absent"   # h+k+l=1
        assert run_check(230, 1, 1, 1) == "absent"   # h+k+l=3
        # 0kl: k,l both even (permutable for cubic)
        assert run_check(230, 0, 1, 1) == "absent"   # k=1,l=1 odd
        assert run_check(230, 0, 2, 2) == "allowed"  # k=2,l=2 even; h+k+l=4
        assert run_check(230, 0, 2, 4) == "allowed"  # k=2,l=4 even; h+k+l=6
        # h00: h=4n
        assert run_check(230, 2, 0, 0) == "absent"   # h=2, not 4n
        assert run_check(230, 4, 0, 0) == "allowed"  # h=4
        # hhl: 2h+l=4n
        assert run_check(230, 1, 1, 2) == "allowed"  # 2+2=4; h+k+l=4
        assert run_check(230, 1, 1, 0) == "absent"   # 2+0=2, not 4n
        assert run_check(230, 2, 2, 0) == "allowed"  # 4+0=4; h+k+l=4


# ================================================================
# Batch check
# ================================================================
class TestBatchCheck:
    def test_batch_p21c(self):
        """Batch check several reflections for P21/c."""
        refs = [(1, 0, 1), (1, 0, 2), (0, 1, 0), (0, 2, 0), (1, 1, 1)]
        results = run_batch(14, refs)
        assert len(results) == 5
        statuses = [r["status"] for r in results]
        assert statuses == ["absent", "allowed", "absent", "allowed", "allowed"]

    def test_batch_fm3m(self):
        """Batch check F-centering conditions for Fm-3m."""
        refs = [(1, 1, 1), (1, 0, 0), (2, 0, 0), (2, 1, 1)]
        results = run_batch(225, refs)
        statuses = [r["status"] for r in results]
        assert statuses == ["allowed", "absent", "allowed", "absent"]


# ================================================================
# Identify (inverse problem)
# ================================================================
class TestIdentify:
    def test_identify_monoclinic_p21c(self):
        """Observations that uniquely identify P21/c (14) in monoclinic."""
        observations = [
            (1, 0, 3, "absent"),     # h0l l=3 odd → c-glide
            (1, 0, 2, "observed"),   # h0l l=2 even → allowed
            (2, 0, 1, "absent"),     # h0l l=1 odd
            (0, 1, 0, "absent"),     # 0k0 k=1 odd → 21 screw
            (0, 2, 0, "observed"),   # 0k0 k=2 even
            (1, 2, 0, "observed"),   # hk0 h+k=3 odd → excludes C centering
            (1, 1, 1, "observed"),   # general
            (2, 3, 1, "observed"),   # general
        ]
        result = run_identify("monoclinic", observations)
        sgs = result["compatible_space_groups"]
        assert 14 in sgs, f"P21/c (14) must be compatible, got {sgs}"
        # Exclude key alternatives
        assert 4 not in sgs, "P21 (4) has no h0l condition"
        assert 7 not in sgs, "Pc (7) has no 0k0 condition"
        assert 13 not in sgs, "P2/c (13) has no 0k0 condition"
        assert 15 not in sgs, "C2/c (15) is excluded by (1,2,0) observed"

    def test_identify_cubic_ia3d(self):
        """Observations that uniquely identify Ia-3d (230) in cubic."""
        observations = [
            (1, 0, 0, "absent"),     # h+k+l=1 odd → excludes P, F
            (2, 0, 0, "absent"),     # h=2, not 4n → excludes I groups with h00:h=2n
            (4, 0, 0, "observed"),   # h=4, 4n → allowed
            (0, 1, 1, "absent"),     # 0kl k=1,l=1 odd
            (0, 2, 2, "observed"),   # 0kl k=2,l=2 even
            (0, 1, 3, "absent"),     # 0kl k=1 odd → k,l=2n (distinguishes from I-43d)
            (1, 1, 0, "absent"),     # hk0 h=1,k=1 odd
            (2, 2, 0, "observed"),   # hk0 h=2,k=2 even; hhl 2*2+0=4
            (1, 1, 2, "observed"),   # hhl 2+2=4, 4n
        ]
        result = run_identify("cubic", observations)
        sgs = result["compatible_space_groups"]
        assert sgs == [230], f"Only Ia-3d (230) should be compatible, got {sgs}"


# ================================================================
# Edge cases
# ================================================================
class TestEdgeCases:
    def test_negative_indices(self):
        """Negative indices must be handled correctly."""
        # P21/c: (-1,0,1) and (1,0,-1) both have |l|=1 odd in h0l
        assert run_check(14, -1, 0, 1) == "absent"
        assert run_check(14, 1, 0, -1) == "absent"
        assert run_check(14, -1, 0, 2) == "allowed"
        assert run_check(14, 0, -3, 0) == "absent"  # 0k0 |k|=3 odd

    def test_large_indices(self):
        """Large Miller indices should work correctly."""
        # Fm-3m: all even → allowed, mixed → absent
        assert run_check(225, 10, 10, 10) == "allowed"
        assert run_check(225, 10, 10, 11) == "absent"
        # P21/c: h0l l=17 odd
        assert run_check(14, 5, 0, 17) == "absent"
        assert run_check(14, 5, 0, 18) == "allowed"
