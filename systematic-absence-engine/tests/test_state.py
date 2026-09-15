"""
Tests for the systematic absence engine /app/refcond.py.
Covers all 7 crystal systems, derive (symbolic conditions), and
check-transformed (basis change) commands.
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


def run_derive(sg):
    """Run derive and return dict of {reflection_type: condition}."""
    result = subprocess.run(
        ["python3", "/app/refcond.py", "derive", str(sg)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"derive failed: {result.stderr}"
    data = json.loads(result.stdout.strip())
    assert "conditions" in data
    return {c["reflection_type"]: c["condition"] for c in data["conditions"]}


def run_transformed(sg, P, reflections):
    """Run check-transformed and return list of statuses."""
    stdin_data = "\n".join(f"{h} {k} {l}" for h, k, l in reflections)
    result = subprocess.run(
        ["python3", "/app/refcond.py", "check-transformed",
         str(sg), json.dumps(P)],
        capture_output=True, text=True, input=stdin_data, timeout=120,
    )
    assert result.returncode == 0, f"check-transformed failed: {result.stderr}"
    lines = [x.strip() for x in result.stdout.strip().split("\n") if x.strip()]
    return lines


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
        assert run_check(7, 0, 1, 0) == "allowed"
        assert run_check(7, 0, 3, 0) == "allowed"

    def test_p21c_full(self):
        """P21/c (14): h0l: l=2n, 0k0: k=2n, 00l: l=2n."""
        assert run_check(14, 1, 0, 1) == "absent"
        assert run_check(14, 1, 0, 2) == "allowed"
        assert run_check(14, 3, 0, 5) == "absent"
        assert run_check(14, 2, 0, 4) == "allowed"
        assert run_check(14, 0, 1, 0) == "absent"
        assert run_check(14, 0, 2, 0) == "allowed"
        assert run_check(14, 0, 5, 0) == "absent"
        assert run_check(14, 0, 6, 0) == "allowed"
        assert run_check(14, 0, 0, 1) == "absent"
        assert run_check(14, 0, 0, 2) == "allowed"
        assert run_check(14, 1, 1, 1) == "allowed"
        assert run_check(14, 2, 3, 5) == "allowed"

    def test_c2c_centering_and_glide(self):
        """C2/c (15): hkl: h+k=2n, h0l: l=2n, 0k0: k=2n."""
        assert run_check(15, 1, 0, 0) == "absent"
        assert run_check(15, 1, 1, 0) == "allowed"
        assert run_check(15, 2, 1, 1) == "absent"
        assert run_check(15, 2, 2, 1) == "allowed"
        assert run_check(15, 2, 0, 1) == "absent"
        assert run_check(15, 2, 0, 2) == "allowed"
        assert run_check(15, 0, 1, 0) == "absent"
        assert run_check(15, 0, 2, 0) == "allowed"


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
        assert run_check(19, 1, 1, 1) == "allowed"
        assert run_check(19, 1, 2, 3) == "allowed"

    def test_pnma_zonal_and_serial(self):
        """Pnma (62): 0kl: k+l=2n, hk0: h=2n, h00: h=2n, 0k0: k=2n, 00l: l=2n."""
        assert run_check(62, 0, 1, 0) == "absent"
        assert run_check(62, 0, 1, 1) == "allowed"
        assert run_check(62, 0, 2, 1) == "absent"
        assert run_check(62, 0, 3, 3) == "allowed"
        assert run_check(62, 1, 1, 0) == "absent"
        assert run_check(62, 2, 1, 0) == "allowed"
        assert run_check(62, 3, 2, 0) == "absent"
        assert run_check(62, 4, 3, 0) == "allowed"
        assert run_check(62, 1, 0, 0) == "absent"
        assert run_check(62, 2, 0, 0) == "allowed"
        assert run_check(62, 0, 0, 1) == "absent"
        assert run_check(62, 0, 0, 2) == "allowed"
        assert run_check(62, 1, 0, 1) == "allowed"
        assert run_check(62, 3, 0, 5) == "allowed"


# ================================================================
# Tetragonal — I centering, screw axes
# ================================================================
class TestTetragonal:
    def test_i4mmm_centering(self):
        """I4/mmm (139): hkl: h+k+l=2n from I centering."""
        assert run_check(139, 1, 0, 0) == "absent"
        assert run_check(139, 1, 1, 0) == "allowed"
        assert run_check(139, 1, 1, 1) == "absent"
        assert run_check(139, 2, 0, 0) == "allowed"
        assert run_check(139, 2, 1, 0) == "absent"
        assert run_check(139, 3, 2, 1) == "allowed"

    def test_p42_screw(self):
        """P42 (77): 00l: l=2n from 42 screw."""
        assert run_check(77, 0, 0, 1) == "absent"
        assert run_check(77, 0, 0, 2) == "allowed"
        assert run_check(77, 0, 0, 3) == "absent"
        assert run_check(77, 0, 0, 4) == "allowed"
        assert run_check(77, 1, 0, 0) == "allowed"
        assert run_check(77, 1, 1, 0) == "allowed"


# ================================================================
# Trigonal — R centering (hexagonal axes, obverse)
# ================================================================
class TestTrigonal:
    def test_r_bar3_centering(self):
        """R-3 (148): -h+k+l=3n in hexagonal obverse setting."""
        assert run_check(148, 1, 0, 0) == "absent"
        assert run_check(148, 1, 1, 0) == "allowed"
        assert run_check(148, 1, 0, 1) == "allowed"
        assert run_check(148, 0, 0, 1) == "absent"
        assert run_check(148, 0, 0, 3) == "allowed"
        assert run_check(148, 1, 2, 0) == "absent"
        assert run_check(148, 0, 1, 2) == "allowed"


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
        assert run_check(169, 1, 0, 0) == "allowed"


# ================================================================
# Cubic — F centering, I centering with complex conditions
# ================================================================
class TestCubic:
    def test_fm3m_f_centering(self):
        """Fm-3m (225): hkl all even or all odd (F centering)."""
        assert run_check(225, 1, 1, 1) == "allowed"
        assert run_check(225, 2, 0, 0) == "allowed"
        assert run_check(225, 2, 2, 2) == "allowed"
        assert run_check(225, 1, 0, 0) == "absent"
        assert run_check(225, 1, 1, 0) == "absent"
        assert run_check(225, 2, 1, 0) == "absent"
        assert run_check(225, 2, 1, 1) == "absent"

    def test_ia3d_complex(self):
        """Ia-3d (230): hkl: h+k+l=2n, 0kl: k,l=2n, hhl: 2h+l=4n, h00: h=4n."""
        assert run_check(230, 1, 0, 0) == "absent"
        assert run_check(230, 1, 1, 1) == "absent"
        assert run_check(230, 0, 1, 1) == "absent"
        assert run_check(230, 0, 2, 2) == "allowed"
        assert run_check(230, 0, 2, 4) == "allowed"
        assert run_check(230, 2, 0, 0) == "absent"
        assert run_check(230, 4, 0, 0) == "allowed"
        assert run_check(230, 1, 1, 2) == "allowed"
        assert run_check(230, 1, 1, 0) == "absent"
        assert run_check(230, 2, 2, 0) == "allowed"


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
            (1, 0, 3, "absent"),
            (1, 0, 2, "observed"),
            (2, 0, 1, "absent"),
            (0, 1, 0, "absent"),
            (0, 2, 0, "observed"),
            (1, 2, 0, "observed"),
            (1, 1, 1, "observed"),
            (2, 3, 1, "observed"),
        ]
        result = run_identify("monoclinic", observations)
        sgs = result["compatible_space_groups"]
        assert 14 in sgs, f"P21/c (14) must be compatible, got {sgs}"
        assert 4 not in sgs, "P21 (4) has no h0l condition"
        assert 7 not in sgs, "Pc (7) has no 0k0 condition"
        assert 13 not in sgs, "P2/c (13) has no 0k0 condition"
        assert 15 not in sgs, "C2/c (15) is excluded by (1,2,0) observed"

    def test_identify_cubic_ia3d(self):
        """Observations that uniquely identify Ia-3d (230) in cubic."""
        observations = [
            (1, 0, 0, "absent"),
            (2, 0, 0, "absent"),
            (4, 0, 0, "observed"),
            (0, 1, 1, "absent"),
            (0, 2, 2, "observed"),
            (0, 1, 3, "absent"),
            (1, 1, 0, "absent"),
            (2, 2, 0, "observed"),
            (1, 1, 2, "observed"),
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
        assert run_check(14, -1, 0, 1) == "absent"
        assert run_check(14, 1, 0, -1) == "absent"
        assert run_check(14, -1, 0, 2) == "allowed"
        assert run_check(14, 0, -3, 0) == "absent"

    def test_large_indices(self):
        """Large Miller indices should work correctly."""
        assert run_check(225, 10, 10, 10) == "allowed"
        assert run_check(225, 10, 10, 11) == "absent"
        assert run_check(14, 5, 0, 17) == "absent"
        assert run_check(14, 5, 0, 18) == "allowed"

    def test_null_reflection(self):
        """(0,0,0) is always absent."""
        assert run_check(1, 0, 0, 0) == "absent"
        assert run_check(225, 0, 0, 0) == "absent"


# ================================================================
# Derive — symbolic condition extraction
# ================================================================
class TestDerive:
    def test_p1_no_conditions(self):
        """P1 (1): no systematic absences, empty conditions list."""
        conds = run_derive(1)
        assert len(conds) == 0, f"P1 should have no conditions, got {conds}"

    def test_p21c_derive(self):
        """P21/c (14): h0l: l=2n, 0k0: k=2n, 00l: l=2n."""
        conds = run_derive(14)
        assert conds.get("h0l") == "l=2n", f"h0l wrong: {conds.get('h0l')}"
        assert conds.get("0k0") == "k=2n", f"0k0 wrong: {conds.get('0k0')}"
        assert conds.get("00l") == "l=2n", f"00l wrong: {conds.get('00l')}"
        assert "hkl" not in conds, "P21/c has no integral condition"

    def test_p212121_derive(self):
        """P212121 (19): h00: h=2n, 0k0: k=2n, 00l: l=2n."""
        conds = run_derive(19)
        assert conds.get("h00") == "h=2n"
        assert conds.get("0k0") == "k=2n"
        assert conds.get("00l") == "l=2n"
        assert "hkl" not in conds

    def test_i4mmm_derive(self):
        """I4/mmm (139): integral h+k+l=2n plus derived serial/zonal."""
        conds = run_derive(139)
        assert conds.get("hkl") == "h+k+l=2n"
        assert conds.get("hhl") == "l=2n", f"hhl wrong: {conds.get('hhl')}"
        assert conds.get("h00") == "h=2n"
        assert conds.get("0k0") == "k=2n"
        assert conds.get("00l") == "l=2n"

    def test_r3_derive(self):
        """R-3 (148): integral -h+k+l=3n plus R-centering on subsets."""
        conds = run_derive(148)
        assert conds.get("hkl") == "-h+k+l=3n"
        assert conds.get("00l") == "l=3n"
        assert conds.get("hhl") == "l=3n"

    def test_p61_derive(self):
        """P61 (169): only 00l: l=6n."""
        conds = run_derive(169)
        assert conds.get("00l") == "l=6n"
        assert "hkl" not in conds
        assert "h0l" not in conds

    def test_ia3d_derive(self):
        """Ia-3d (230): complex conditions from I centering + d-glide."""
        conds = run_derive(230)
        assert conds.get("hkl") == "h+k+l=2n"
        assert conds.get("hhl") == "2h+l=4n"
        assert conds.get("h00") == "h=4n"
        assert conds.get("0kl") == "k=2n,l=2n"

    def test_fm3m_derive(self):
        """Fm-3m (225): F centering conditions."""
        conds = run_derive(225)
        assert conds.get("hkl") == "h+k=2n,h+l=2n,k+l=2n"
        assert conds.get("h00") == "h=2n"


# ================================================================
# Check-transformed — basis change
# ================================================================
class TestCheckTransformed:
    def test_swap_axes_p21c(self):
        """Swap a,b axes for P21/c (14).
        P = [[0,1,0],[1,0,0],[0,0,1]]: a'=b, b'=a, c'=c.
        h_old = h_new @ P^{-1} = h_new @ P (self-inverse permutation).
        """
        P = [[0, 1, 0], [1, 0, 0], [0, 0, 1]]
        refs = [
            (1, 0, 0),  # old=(0,1,0): 0k0 k=1 odd -> absent
            (2, 0, 0),  # old=(0,2,0): 0k0 k=2 even -> allowed
            (0, 0, 1),  # old=(0,0,1): 00l l=1 odd -> absent
            (0, 0, 2),  # old=(0,0,2): 00l l=2 even -> allowed
            (0, 1, 1),  # old=(1,0,1): h0l l=1 odd -> absent
            (0, 1, 2),  # old=(1,0,2): h0l l=2 even -> allowed
        ]
        expected = ["absent", "allowed", "absent", "allowed", "absent", "allowed"]
        assert run_transformed(14, P, refs) == expected

    def test_double_c_p61(self):
        """Double c axis for P61 (169): 00l: l=6n in standard setting.
        P = [[1,0,0],[0,1,0],[0,0,2]]: c' = 2c.
        h_old = h_new @ P^{-1}, so new (0,0,l') -> old (0,0,l'/2).
        """
        P = [[1, 0, 0], [0, 1, 0], [0, 0, 2]]
        refs = [
            (0, 0, 1),   # old=(0,0,0.5): non-lattice -> absent
            (0, 0, 2),   # old=(0,0,1): l=1 not 6n -> absent
            (0, 0, 12),  # old=(0,0,6): l=6, 6n -> allowed
            (1, 0, 0),   # old=(1,0,0): general -> allowed
            (0, 0, 3),   # old=(0,0,1.5): non-lattice -> absent
        ]
        expected = ["absent", "absent", "allowed", "allowed", "absent"]
        assert run_transformed(169, P, refs) == expected

    def test_shear_c2c(self):
        """Non-trivial shear for C2/c (15).
        P = [[1,1,0],[0,1,0],[0,0,1]]: a'=a+b, b'=b, c'=c.
        P^{-1} = [[1,-1,0],[0,1,0],[0,0,1]].
        h_old = h_new @ P^{-1}.
        """
        P = [[1, 1, 0], [0, 1, 0], [0, 0, 1]]
        # C2/c conditions: hkl: h+k=2n, h0l: l=2n, 0k0: k=2n
        refs = [
            (1, 1, 0),  # old=(1,0,0): h+k=1 odd -> absent (centering)
            (1, 0, 0),  # old=(1,-1,0): h+k=0 even -> allowed
            (0, 1, 0),  # old=(0,1,0): 0k0 k=1 -> absent
            (0, 2, 0),  # old=(0,2,0): 0k0 k=2, h+k=2 -> allowed
            (2, 2, 1),  # old=(2,0,1): h+k=2 even, h0l l=1 odd -> absent
            (2, 2, 2),  # old=(2,0,2): h+k=2 even, h0l l=2 even -> allowed
        ]
        expected = ["absent", "allowed", "absent", "allowed", "absent", "allowed"]
        assert run_transformed(15, P, refs) == expected

    def test_identity_transform(self):
        """Identity P should reproduce standard check results."""
        P = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        refs = [(1, 0, 1), (1, 0, 2), (0, 1, 0), (0, 2, 0)]
        expected = ["absent", "allowed", "absent", "allowed"]
        assert run_transformed(14, P, refs) == expected

    def test_transform_cubic_permutation(self):
        """Cyclic permutation of axes for Fm-3m (225).
        P = [[0,0,1],[1,0,0],[0,1,0]]: a'=b, b'=c, c'=a.
        P^{-1} = [[0,1,0],[0,0,1],[1,0,0]].
        h_old = h_new @ P^{-1} = (l', h', k').
        F centering is invariant under axis permutation.
        """
        P = [[0, 0, 1], [1, 0, 0], [0, 1, 0]]
        refs = [
            (1, 1, 1),  # old=(1,1,1): all odd -> allowed
            (1, 0, 0),  # old=(0,1,0): mixed -> absent
            (2, 1, 0),  # old=(0,2,1): mixed parity -> absent
            (2, 0, 2),  # old=(2,2,0): all even -> allowed
        ]
        expected = ["allowed", "absent", "absent", "allowed"]
        assert run_transformed(225, P, refs) == expected
