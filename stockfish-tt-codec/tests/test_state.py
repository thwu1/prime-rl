"""Tests for Stockfish Transposition Table Simulator.

Verifies that Stockfish was built successfully and that /app/tt_codec.py
faithfully reimplements TTEntry encoding, decoding, cluster probing,
replacement strategy, ply-adjusted score storage, and full cluster
lifecycle simulation from the C++ source.

"""

import os
import subprocess
import sys
import importlib

import pytest

sys.path.insert(0, "/app")
tt = importlib.import_module("tt_codec")


# ============================================================
# Stockfish build verification
# ============================================================


class TestStockfishBuild:
    BINARY = "/app/stockfish/src/stockfish"

    def test_binary_exists(self):
        assert os.path.isfile(self.BINARY), \
            f"Stockfish binary not found at {self.BINARY}"

    def test_binary_executable(self):
        assert os.access(self.BINARY, os.X_OK), \
            f"Stockfish binary at {self.BINARY} is not executable"

    def test_uci_handshake(self):
        proc = subprocess.run(
            [self.BINARY],
            input="uci\nquit\n",
            capture_output=True, text=True, timeout=15,
        )
        assert "uciok" in proc.stdout, \
            "Stockfish binary did not respond with 'uciok' to UCI handshake"


# ============================================================
# Constants validation
# ============================================================


class TestConstants:
    def test_depth_none(self):
        assert tt.DEPTH_NONE == -3

    def test_depth_unsearched(self):
        assert tt.DEPTH_UNSEARCHED == -2

    def test_max_ply(self):
        assert tt.MAX_PLY == 246

    def test_bound_none(self):
        assert tt.BOUND_NONE == 0

    def test_bound_upper(self):
        assert tt.BOUND_UPPER == 1

    def test_bound_lower(self):
        assert tt.BOUND_LOWER == 2

    def test_bound_exact(self):
        assert tt.BOUND_EXACT == 3

    def test_generation_bits(self):
        assert tt.GENERATION_BITS == 5

    def test_generation_mask(self):
        assert tt.GENERATION_MASK == 31

    def test_bound_shift(self):
        assert tt.BOUND_SHIFT == 5

    def test_bound_mask(self):
        assert tt.BOUND_MASK == 0x60

    def test_pv_shift(self):
        assert tt.PV_SHIFT == 7

    def test_pv_mask(self):
        assert tt.PV_MASK == 0x80

    def test_cluster_size(self):
        assert tt.CLUSTER_SIZE == 3

    def test_value_none(self):
        assert tt.VALUE_NONE == 32002

    def test_value_infinite(self):
        assert tt.VALUE_INFINITE == 32001

    def test_value_mate(self):
        assert tt.VALUE_MATE == 32000

    def test_value_mate_in_max_ply(self):
        assert tt.VALUE_MATE_IN_MAX_PLY == 31754

    def test_value_mated_in_max_ply(self):
        assert tt.VALUE_MATED_IN_MAX_PLY == -31754

    def test_value_tb(self):
        assert tt.VALUE_TB == 31753

    def test_value_tb_win(self):
        assert tt.VALUE_TB_WIN_IN_MAX_PLY == 31507

    def test_value_tb_loss(self):
        assert tt.VALUE_TB_LOSS_IN_MAX_PLY == -31507

    def test_derived_consistency(self):
        """Constants must satisfy the derivation chain from types.h."""
        assert tt.VALUE_MATE_IN_MAX_PLY == tt.VALUE_MATE - tt.MAX_PLY
        assert tt.VALUE_MATED_IN_MAX_PLY == -tt.VALUE_MATE_IN_MAX_PLY
        assert tt.VALUE_TB == tt.VALUE_MATE_IN_MAX_PLY - 1
        assert tt.VALUE_TB_WIN_IN_MAX_PLY == tt.VALUE_TB - tt.MAX_PLY
        assert tt.VALUE_TB_LOSS_IN_MAX_PLY == -tt.VALUE_TB_WIN_IN_MAX_PLY


# ============================================================
# pack_gen_bound / unpack_gen_bound
# ============================================================


class TestGenBoundPacking:
    def test_pack_exact_pv(self):
        assert tt.pack_gen_bound(5, tt.BOUND_EXACT, True) == 229

    def test_pack_zeros(self):
        assert tt.pack_gen_bound(0, tt.BOUND_NONE, False) == 0

    def test_pack_lower_no_pv(self):
        assert tt.pack_gen_bound(31, tt.BOUND_LOWER, False) == 95

    def test_pack_upper_pv(self):
        assert tt.pack_gen_bound(15, tt.BOUND_UPPER, True) == 175

    def test_unpack_229(self):
        gen, bound, is_pv = tt.unpack_gen_bound(229)
        assert gen == 5
        assert bound == tt.BOUND_EXACT
        assert is_pv is True

    def test_unpack_95(self):
        gen, bound, is_pv = tt.unpack_gen_bound(95)
        assert gen == 31
        assert bound == tt.BOUND_LOWER
        assert is_pv is False

    def test_unpack_175(self):
        gen, bound, is_pv = tt.unpack_gen_bound(175)
        assert gen == 15
        assert bound == tt.BOUND_UPPER
        assert is_pv is True

    def test_unpack_zeros(self):
        gen, bound, is_pv = tt.unpack_gen_bound(0)
        assert gen == 0
        assert bound == tt.BOUND_NONE
        assert is_pv is False

    def test_roundtrip_exhaustive(self):
        """Every valid (generation, bound, is_pv) combo must round-trip."""
        for gen in range(32):
            for bound in range(4):
                for pv in [True, False]:
                    packed = tt.pack_gen_bound(gen, bound, pv)
                    g, b, p = tt.unpack_gen_bound(packed)
                    assert g == gen, f"gen mismatch at ({gen},{bound},{pv})"
                    assert b == bound, f"bound mismatch at ({gen},{bound},{pv})"
                    assert p == pv, f"pv mismatch at ({gen},{bound},{pv})"


# ============================================================
# encode_depth / decode_depth
# ============================================================


class TestDepthCodec:
    def test_encode_normal(self):
        assert tt.encode_depth(10) == 13

    def test_encode_qs(self):
        assert tt.encode_depth(0) == 3

    def test_encode_unsearched(self):
        assert tt.encode_depth(-2) == 1

    def test_encode_none(self):
        assert tt.encode_depth(-3) == 0

    def test_decode_13(self):
        assert tt.decode_depth(13) == 10

    def test_decode_0(self):
        assert tt.decode_depth(0) == -3

    def test_roundtrip(self):
        for d in range(-3, 60):
            assert tt.decode_depth(tt.encode_depth(d)) == d


# ============================================================
# relative_age
# ============================================================


class TestRelativeAge:
    def test_same_generation(self):
        gb = tt.pack_gen_bound(5, tt.BOUND_EXACT, True)
        assert tt.relative_age(5, gb) == 0

    def test_newer_by_5(self):
        gb = tt.pack_gen_bound(5, tt.BOUND_EXACT, True)
        assert tt.relative_age(10, gb) == 5

    def test_wrap_around(self):
        gb = tt.pack_gen_bound(5, tt.BOUND_EXACT, True)
        assert tt.relative_age(3, gb) == 30

    def test_wrap_around_from_zero(self):
        gb = tt.pack_gen_bound(5, tt.BOUND_NONE, False)
        assert tt.relative_age(0, gb) == 27

    def test_max_age(self):
        gb = tt.pack_gen_bound(0, tt.BOUND_NONE, False)
        assert tt.relative_age(31, gb) == 31

    def test_bound_pv_bits_ignored(self):
        """Different bound/PV bits with same generation must give same age."""
        gb_plain = tt.pack_gen_bound(10, tt.BOUND_NONE, False)
        gb_fancy = tt.pack_gen_bound(10, tt.BOUND_EXACT, True)
        age_plain = tt.relative_age(15, gb_plain)
        age_fancy = tt.relative_age(15, gb_fancy)
        assert age_plain == age_fancy == 5

    def test_all_generations_wrap_correctly(self):
        """For every generation pair, age must equal (curr-entry) mod 32."""
        for entry_gen in range(32):
            gb = tt.pack_gen_bound(entry_gen, tt.BOUND_LOWER, True)
            for curr_gen in range(32):
                expected = (curr_gen - entry_gen) % 32
                assert tt.relative_age(curr_gen, gb) == expected, \
                    f"Failed for curr={curr_gen}, entry_gen={entry_gen}"


# ============================================================
# encode_entry / decode_entry
# ============================================================


class TestEntryCodec:
    def test_basic_size(self):
        data = tt.encode_entry(
            key64=0x1234567890ABCDEF,
            depth=10, is_pv=True, bound=tt.BOUND_EXACT,
            move16=0x1234, value=100, eval_value=150,
            generation=5,
        )
        assert isinstance(data, (bytes, bytearray))
        assert len(data) == 10

    def test_exact_bytes(self):
        data = tt.encode_entry(
            key64=0x1234567890ABCDEF,
            depth=10, is_pv=True, bound=tt.BOUND_EXACT,
            move16=0x1234, value=100, eval_value=150,
            generation=5,
        )
        expected = bytes(
            [0xEF, 0xCD, 0x0D, 0xE5, 0x34, 0x12, 0x64, 0x00, 0x96, 0x00]
        )
        assert data == expected

    def test_negative_values(self):
        data = tt.encode_entry(
            key64=0, depth=5, is_pv=False, bound=tt.BOUND_UPPER,
            move16=0, value=-100, eval_value=-200,
            generation=0,
        )
        decoded = tt.decode_entry(data)
        assert decoded["value"] == -100
        assert decoded["eval_value"] == -200

    def test_roundtrip_typical(self):
        data = tt.encode_entry(
            key64=0xDEADBEEFCAFEBABE,
            depth=20, is_pv=False, bound=tt.BOUND_LOWER,
            move16=0xABCD, value=-500, eval_value=300,
            generation=17,
        )
        d = tt.decode_entry(data)
        assert d["key16"] == 0xBABE
        assert d["depth"] == 20
        assert d["depth8"] == 23
        assert d["is_pv"] is False
        assert d["bound"] == tt.BOUND_LOWER
        assert d["generation"] == 17
        assert d["move16"] == 0xABCD
        assert d["value"] == -500
        assert d["eval_value"] == 300

    def test_mate_score(self):
        data = tt.encode_entry(
            key64=0, depth=15, is_pv=True, bound=tt.BOUND_EXACT,
            move16=100, value=31900, eval_value=0,
            generation=0,
        )
        d = tt.decode_entry(data)
        assert d["value"] == 31900

    def test_negative_mate_score(self):
        data = tt.encode_entry(
            key64=0, depth=15, is_pv=True, bound=tt.BOUND_EXACT,
            move16=100, value=-31900, eval_value=0,
            generation=0,
        )
        d = tt.decode_entry(data)
        assert d["value"] == -31900

    def test_max_generation(self):
        data = tt.encode_entry(
            key64=0xFFFFFFFFFFFFFFFF,
            depth=0, is_pv=True, bound=tt.BOUND_EXACT,
            move16=0xFFFF, value=-32000, eval_value=32000,
            generation=31,
        )
        d = tt.decode_entry(data)
        assert d["generation"] == 31
        assert d["key16"] == 0xFFFF
        assert d["value"] == -32000
        assert d["eval_value"] == 32000

    def test_unoccupied_entry(self):
        data = tt.encode_entry(
            key64=0x1111, depth=-3, is_pv=False, bound=tt.BOUND_NONE,
            move16=0, value=0, eval_value=0,
            generation=0,
        )
        d = tt.decode_entry(data)
        assert d["depth8"] == 0
        assert d["depth"] == -3

    def test_gen_bound8_in_decoded(self):
        data = tt.encode_entry(
            key64=0, depth=10, is_pv=True, bound=tt.BOUND_EXACT,
            move16=0, value=0, eval_value=0,
            generation=5,
        )
        d = tt.decode_entry(data)
        assert d["gen_bound8"] == tt.pack_gen_bound(5, tt.BOUND_EXACT, True)


# ============================================================
# cluster_index
# ============================================================


class TestClusterIndex:
    def test_zero_key(self):
        assert tt.cluster_index(0, 524288) == 0

    def test_max_key(self):
        assert tt.cluster_index(0xFFFFFFFFFFFFFFFF, 524288) == 524287

    def test_reference_computation(self):
        key = 0x1234567890ABCDEF
        count = 524288
        expected = (key * count) >> 64
        assert tt.cluster_index(key, count) == expected

    def test_power_of_two_equivalence(self):
        key = 0xABCDEF0123456789
        assert tt.cluster_index(key, 1024) == key >> 54
        assert tt.cluster_index(key, 4096) == key >> 52
        assert tt.cluster_index(key, 1) == 0

    def test_large_cluster_count(self):
        key = 0x8000000000000000
        count = 0x100000
        expected = (key * count) >> 64
        assert tt.cluster_index(key, count) == expected


# ============================================================
# should_replace
# ============================================================


class TestShouldReplace:
    @staticmethod
    def _entry(key16, depth, generation, bound, is_pv=False):
        return {
            "key16": key16,
            "depth8": tt.encode_depth(depth),
            "gen_bound8": tt.pack_gen_bound(generation, bound, is_pv),
        }

    def test_exact_bound_always_replaces(self):
        existing = self._entry(100, 20, 5, tt.BOUND_LOWER)
        assert tt.should_replace(existing, 100, 5, tt.BOUND_EXACT, False, 5) is True

    def test_different_key_replaces(self):
        existing = self._entry(100, 20, 5, tt.BOUND_LOWER)
        assert tt.should_replace(existing, 0x65, 5, tt.BOUND_LOWER, False, 5) is True

    def test_old_generation_replaces(self):
        existing = self._entry(100, 20, 3, tt.BOUND_LOWER)
        assert tt.should_replace(existing, 100, 5, tt.BOUND_LOWER, False, 5) is True

    def test_deep_entry_not_replaced(self):
        existing = self._entry(100, 30, 5, tt.BOUND_LOWER)
        assert tt.should_replace(existing, 100, 5, tt.BOUND_LOWER, False, 5) is False

    def test_pv_bonus_enables_replace(self):
        existing = self._entry(100, 12, 5, tt.BOUND_LOWER)
        assert tt.should_replace(existing, 100, 10, tt.BOUND_LOWER, True, 5) is True

    def test_near_depth_replaces(self):
        existing = self._entry(100, 10, 5, tt.BOUND_LOWER)
        assert tt.should_replace(existing, 100, 8, tt.BOUND_LOWER, False, 5) is True

    def test_much_shallower_does_not_replace(self):
        existing = self._entry(100, 20, 5, tt.BOUND_LOWER)
        assert tt.should_replace(existing, 100, 5, tt.BOUND_LOWER, False, 5) is False

    def test_depth_boundary_exact(self):
        existing = self._entry(100, 10, 5, tt.BOUND_LOWER)
        assert tt.should_replace(existing, 100, 6, tt.BOUND_LOWER, False, 5) is False

    def test_depth_boundary_just_above(self):
        existing = self._entry(100, 10, 5, tt.BOUND_LOWER)
        assert tt.should_replace(existing, 100, 7, tt.BOUND_LOWER, False, 5) is True

    def test_wrapped_generation_replaces(self):
        existing = self._entry(100, 20, 30, tt.BOUND_LOWER)
        assert tt.should_replace(existing, 100, 5, tt.BOUND_LOWER, False, 2) is True


# ============================================================
# select_victim
# ============================================================


class TestSelectVictim:
    @staticmethod
    def _entry(depth, generation, bound=tt.BOUND_LOWER, is_pv=False):
        return {
            "depth8": tt.encode_depth(depth),
            "gen_bound8": tt.pack_gen_bound(generation, bound, is_pv),
        }

    def test_shallowest_evicted(self):
        entries = [
            self._entry(15, 5),
            self._entry(20, 5),
            self._entry(10, 5),
        ]
        assert tt.select_victim(entries, 5) == 2

    def test_oldest_evicted(self):
        entries = [
            self._entry(10, 5),
            self._entry(10, 3),
            self._entry(10, 5),
        ]
        assert tt.select_victim(entries, 5) == 1

    def test_first_on_tie(self):
        entries = [
            self._entry(10, 5),
            self._entry(10, 5),
            self._entry(10, 5),
        ]
        assert tt.select_victim(entries, 5) == 0

    def test_age_dominates_depth(self):
        entries = [
            self._entry(30, 5),
            self._entry(5, 0),
            self._entry(20, 5),
        ]
        assert tt.select_victim(entries, 5) == 1

    def test_negative_scores(self):
        entries = [
            self._entry(2, 0),
            self._entry(3, 1),
            self._entry(1, 0),
        ]
        assert tt.select_victim(entries, 10) == 2


# ============================================================
# apply_secondary_aging
# ============================================================


class TestSecondaryAging:
    @staticmethod
    def _entry(depth, bound, value):
        return {
            "depth8": tt.encode_depth(depth),
            "gen_bound8": tt.pack_gen_bound(0, bound, False),
            "value": value,
        }

    def test_decisive_lower_ages(self):
        entry = self._entry(10, tt.BOUND_LOWER, 31600)
        original_depth8 = entry["depth8"]
        assert tt.apply_secondary_aging(entry) is True
        assert entry["depth8"] == original_depth8 - 1

    def test_decisive_upper_loss_ages(self):
        entry = self._entry(10, tt.BOUND_UPPER, -31600)
        original_depth8 = entry["depth8"]
        assert tt.apply_secondary_aging(entry) is True
        assert entry["depth8"] == original_depth8 - 1

    def test_exact_bound_no_aging(self):
        entry = self._entry(10, tt.BOUND_EXACT, 31600)
        original_depth8 = entry["depth8"]
        assert tt.apply_secondary_aging(entry) is False
        assert entry["depth8"] == original_depth8

    def test_shallow_no_aging(self):
        entry = self._entry(4, tt.BOUND_LOWER, 31600)
        assert tt.apply_secondary_aging(entry) is False

    def test_non_decisive_no_aging(self):
        entry = self._entry(10, tt.BOUND_LOWER, 1000)
        assert tt.apply_secondary_aging(entry) is False

    def test_infinite_no_aging(self):
        entry = self._entry(10, tt.BOUND_LOWER, 32001)
        assert tt.apply_secondary_aging(entry) is False

    def test_boundary_decisive_exact(self):
        entry = self._entry(10, tt.BOUND_LOWER, 31507)
        assert tt.apply_secondary_aging(entry) is True

    def test_boundary_not_decisive(self):
        entry = self._entry(10, tt.BOUND_LOWER, 31506)
        assert tt.apply_secondary_aging(entry) is False

    def test_boundary_depth_passes(self):
        entry = self._entry(5, tt.BOUND_LOWER, 31600)
        assert tt.apply_secondary_aging(entry) is True

    def test_boundary_depth_fails(self):
        entry = self._entry(4, tt.BOUND_LOWER, 31600)
        assert tt.apply_secondary_aging(entry) is False

    def test_negative_decisive_boundary(self):
        entry = self._entry(10, tt.BOUND_UPPER, -31507)
        assert tt.apply_secondary_aging(entry) is True

    def test_negative_not_decisive(self):
        entry = self._entry(10, tt.BOUND_UPPER, -31506)
        assert tt.apply_secondary_aging(entry) is False

    def test_none_bound_ages(self):
        entry = self._entry(10, tt.BOUND_NONE, 31600)
        assert tt.apply_secondary_aging(entry) is True


# ============================================================
# value_to_tt
# ============================================================


class TestValueToTT:
    def test_normal_score_unchanged(self):
        assert tt.value_to_tt(100, 5) == 100

    def test_zero_unchanged(self):
        assert tt.value_to_tt(0, 10) == 0

    def test_negative_normal_unchanged(self):
        assert tt.value_to_tt(-500, 7) == -500

    def test_win_adds_ply(self):
        # 31600 >= VALUE_TB_WIN_IN_MAX_PLY → is_win → v + ply
        assert tt.value_to_tt(31600, 7) == 31607

    def test_loss_subtracts_ply(self):
        # -31600 <= VALUE_TB_LOSS_IN_MAX_PLY → is_loss → v - ply
        assert tt.value_to_tt(-31600, 7) == -31607

    def test_mate_score_adds_ply(self):
        # Mate in 10 from root = VALUE_MATE - 10 = 31990
        assert tt.value_to_tt(31990, 5) == 31995

    def test_mated_score_subtracts_ply(self):
        assert tt.value_to_tt(-31990, 5) == -31995

    def test_boundary_win_exact(self):
        assert tt.value_to_tt(31507, 0) == 31507
        assert tt.value_to_tt(31507, 3) == 31510

    def test_boundary_just_below_win(self):
        # 31506 < VALUE_TB_WIN_IN_MAX_PLY → not adjusted
        assert tt.value_to_tt(31506, 10) == 31506

    def test_boundary_just_above_loss(self):
        # -31506 > VALUE_TB_LOSS_IN_MAX_PLY → not adjusted
        assert tt.value_to_tt(-31506, 10) == -31506

    def test_boundary_loss_exact(self):
        assert tt.value_to_tt(-31507, 0) == -31507
        assert tt.value_to_tt(-31507, 3) == -31510

    def test_zero_ply(self):
        assert tt.value_to_tt(31900, 0) == 31900
        assert tt.value_to_tt(-31900, 0) == -31900


# ============================================================
# value_from_tt
# ============================================================


class TestValueFromTT:
    def test_value_none_passthrough(self):
        assert tt.value_from_tt(tt.VALUE_NONE, 5, 0) == tt.VALUE_NONE

    def test_normal_unchanged(self):
        assert tt.value_from_tt(100, 5, 0) == 100

    def test_zero_unchanged(self):
        assert tt.value_from_tt(0, 10, 50) == 0

    def test_negative_normal_unchanged(self):
        assert tt.value_from_tt(-500, 7, 0) == -500

    def test_win_subtracts_ply(self):
        # v=31737, is_win, not mate, VALUE_TB-31737=16, 100-0=100, 16>100? no
        assert tt.value_from_tt(31737, 7, 0) == 31730

    def test_loss_adds_ply(self):
        # v=-31737, is_loss, not mated, VALUE_TB+(-31737)=16, 100-0=100, 16>100? no
        assert tt.value_from_tt(-31737, 7, 0) == -31730

    def test_mate_downgrade_high_r50c(self):
        # v=31900, is_win, is_mate (>=31754)
        # VALUE_MATE - 31900 = 100, 100 - 90 = 10, 100 > 10 → downgrade
        assert tt.value_from_tt(31900, 5, 90) == tt.VALUE_TB_WIN_IN_MAX_PLY - 1

    def test_mate_no_downgrade_low_r50c(self):
        # v=31995, is_mate, VALUE_MATE-31995=5, 100-0=100, 5>100? no
        assert tt.value_from_tt(31995, 3, 0) == 31992

    def test_tb_downgrade(self):
        # v=31600, is_win, not mate (31600<31754)
        # VALUE_TB-31600=153, 100-60=40, 153>40 → downgrade
        assert tt.value_from_tt(31600, 5, 60) == tt.VALUE_TB_WIN_IN_MAX_PLY - 1

    def test_tb_no_downgrade_close_to_value_tb(self):
        # v=31730, VALUE_TB-31730=23, 100-0=100, 23>100? no
        assert tt.value_from_tt(31730, 5, 0) == 31725

    def test_tb_downgrade_boundary_strict_greater(self):
        # v=31653, VALUE_TB-31653=100, 100-0=100, 100>100? NO (strict >)
        assert tt.value_from_tt(31653, 5, 0) == 31648

    def test_tb_downgrade_boundary_just_below(self):
        # v=31652, VALUE_TB-31652=101, 100-0=100, 101>100? YES → downgrade
        assert tt.value_from_tt(31652, 5, 0) == tt.VALUE_TB_WIN_IN_MAX_PLY - 1

    def test_mated_downgrade_high_r50c(self):
        # v=-31900, is_loss, is_mated (<=−31754)
        # VALUE_MATE+(-31900)=100, 100-90=10, 100>10 → downgrade
        assert tt.value_from_tt(-31900, 5, 90) == tt.VALUE_TB_LOSS_IN_MAX_PLY + 1

    def test_mated_no_downgrade_low_r50c(self):
        # v=-31995, VALUE_MATE+(-31995)=5, 100-0=100, 5>100? no
        assert tt.value_from_tt(-31995, 3, 0) == -31992

    def test_tb_loss_downgrade(self):
        # v=-31600, is_loss, not mated
        # VALUE_TB+(-31600)=153, 100-60=40, 153>40 → downgrade
        assert tt.value_from_tt(-31600, 5, 60) == tt.VALUE_TB_LOSS_IN_MAX_PLY + 1

    def test_tb_loss_no_downgrade(self):
        # v=-31730, VALUE_TB+(-31730)=23, 100-0=100, 23>100? no
        assert tt.value_from_tt(-31730, 5, 0) == -31725

    def test_roundtrip_normal_scores(self):
        for v in [-1000, -100, 0, 100, 500, 1000]:
            for ply in [0, 1, 5, 10, 50, 100]:
                assert tt.value_from_tt(tt.value_to_tt(v, ply), ply, 0) == v, \
                    f"Roundtrip failed for v={v}, ply={ply}"

    def test_roundtrip_close_mate(self):
        # Mate in 5 from root: v = 31995, r50c = 0 → no downgrade
        assert tt.value_from_tt(tt.value_to_tt(31995, 3), 3, 0) == 31995

    def test_roundtrip_close_mated(self):
        assert tt.value_from_tt(tt.value_to_tt(-31995, 3), 3, 0) == -31995


# ============================================================
# empty_entry
# ============================================================


class TestEmptyEntry:
    def test_has_required_keys(self):
        e = tt.empty_entry()
        for k in ("key16", "depth8", "gen_bound8", "move16", "value", "eval_value"):
            assert k in e, f"empty_entry missing key '{k}'"

    def test_all_zeros(self):
        e = tt.empty_entry()
        assert e["key16"] == 0
        assert e["depth8"] == 0
        assert e["gen_bound8"] == 0
        assert e["move16"] == 0
        assert e["value"] == 0
        assert e["eval_value"] == 0

    def test_independence(self):
        """Each call returns an independent dict."""
        a = tt.empty_entry()
        b = tt.empty_entry()
        a["depth8"] = 99
        assert b["depth8"] == 0


# ============================================================
# simulate_tt_probe
# ============================================================


class TestSimulateProbe:
    def test_empty_cluster_no_hit(self):
        cluster = [tt.empty_entry() for _ in range(3)]
        hit, data, idx = tt.simulate_tt_probe(cluster, 0x12345678, 0)
        assert hit is False
        assert data is None

    def test_key_match_occupied(self):
        cluster = [tt.empty_entry() for _ in range(3)]
        cluster[1]["key16"] = 0x5678
        cluster[1]["depth8"] = 10
        cluster[1]["gen_bound8"] = tt.pack_gen_bound(0, tt.BOUND_EXACT, True)
        cluster[1]["move16"] = 0x1234
        cluster[1]["value"] = 100
        cluster[1]["eval_value"] = 150

        hit, data, idx = tt.simulate_tt_probe(cluster, 0xABCD5678, 0)
        assert hit is True
        assert idx == 1
        assert data["depth"] == tt.decode_depth(10)
        assert data["bound"] == tt.BOUND_EXACT
        assert data["is_pv"] is True
        assert data["move16"] == 0x1234
        assert data["value"] == 100
        assert data["eval_value"] == 150

    def test_key_match_unoccupied(self):
        """Key matches but depth8=0 → not occupied → hit=False."""
        cluster = [tt.empty_entry() for _ in range(3)]
        cluster[0]["key16"] = 0x5678  # matches but depth8 = 0

        hit, data, idx = tt.simulate_tt_probe(cluster, 0xABCD5678, 0)
        assert hit is False
        assert idx == 0  # still points to the matched entry

    def test_no_match_selects_shallowest_victim(self):
        cluster = [tt.empty_entry() for _ in range(3)]
        for i in range(3):
            cluster[i]["key16"] = i + 1  # none match 0x5678
            cluster[i]["depth8"] = [15, 5, 10][i]
            cluster[i]["gen_bound8"] = tt.pack_gen_bound(0, tt.BOUND_LOWER, False)

        hit, data, idx = tt.simulate_tt_probe(cluster, 0xABCD5678, 0)
        assert hit is False
        assert data is None
        assert idx == 1  # shallowest

    def test_no_match_age_weighted_victim(self):
        """Victim selection uses depth8 - 8*age scoring."""
        cluster = [tt.empty_entry() for _ in range(3)]
        # Entry 0: deep but stale (gen 0, current gen 5 → age 5)
        cluster[0]["key16"] = 0x0001
        cluster[0]["depth8"] = 30
        cluster[0]["gen_bound8"] = tt.pack_gen_bound(0, tt.BOUND_LOWER, False)
        # score = 30 - 8*5 = -10

        # Entry 1: shallow but fresh (gen 5, current gen 5 → age 0)
        cluster[1]["key16"] = 0x0002
        cluster[1]["depth8"] = 5
        cluster[1]["gen_bound8"] = tt.pack_gen_bound(5, tt.BOUND_LOWER, False)
        # score = 5 - 0 = 5

        # Entry 2: medium and fresh
        cluster[2]["key16"] = 0x0003
        cluster[2]["depth8"] = 15
        cluster[2]["gen_bound8"] = tt.pack_gen_bound(5, tt.BOUND_LOWER, False)
        # score = 15 - 0 = 15

        hit, data, idx = tt.simulate_tt_probe(cluster, 0xFFFF9999, 5)
        assert hit is False
        assert idx == 0  # lowest score (-10)

    def test_first_key_match_wins(self):
        """If multiple entries share key16, first match is used."""
        cluster = [tt.empty_entry() for _ in range(3)]
        cluster[0]["key16"] = 0xABCD
        cluster[0]["depth8"] = 5
        cluster[0]["gen_bound8"] = tt.pack_gen_bound(0, tt.BOUND_LOWER, False)
        cluster[1]["key16"] = 0xABCD
        cluster[1]["depth8"] = 20
        cluster[1]["gen_bound8"] = tt.pack_gen_bound(0, tt.BOUND_EXACT, True)

        hit, data, idx = tt.simulate_tt_probe(cluster, 0x0000ABCD, 0)
        assert hit is True
        assert idx == 0
        assert data["depth"] == tt.decode_depth(5)


# ============================================================
# simulate_tt_store
# ============================================================


class TestSimulateStore:
    def test_store_into_empty_cluster(self):
        cluster = [tt.empty_entry() for _ in range(3)]
        tt.simulate_tt_store(
            cluster, 0xDEAD, 100, True, tt.BOUND_EXACT,
            10, 0x1234, 150, 0,
        )

        assert cluster[0]["key16"] == 0xDEAD
        assert cluster[0]["depth8"] == tt.encode_depth(10)
        assert cluster[0]["value"] == 100
        assert cluster[0]["eval_value"] == 150
        assert cluster[0]["move16"] == 0x1234

    def test_move_preservation_same_key_no_move(self):
        """Key matches and new move=0 → old move is preserved."""
        cluster = [tt.empty_entry() for _ in range(3)]
        tt.simulate_tt_store(
            cluster, 0xBEEF, 100, False, tt.BOUND_LOWER,
            10, 0xABCD, 50, 0,
        )
        assert cluster[0]["move16"] == 0xABCD

        # Store again: same key, move=0, deeper depth → replacement succeeds
        tt.simulate_tt_store(
            cluster, 0xBEEF, 200, False, tt.BOUND_UPPER,
            15, 0, 60, 0,
        )
        # Move preserved since key matches and move16=0
        assert cluster[0]["move16"] == 0xABCD
        # But depth/value/bound should update
        assert cluster[0]["depth8"] == tt.encode_depth(15)
        assert cluster[0]["value"] == 200

    def test_move_overwritten_on_key_change(self):
        """When a new position replaces an old one, move is overwritten even if 0."""
        cluster = [tt.empty_entry() for _ in range(3)]
        # Fill all 3 slots
        tt.simulate_tt_store(cluster, 0xAAAA, 100, False, tt.BOUND_LOWER, 5, 0x10, 50, 0)
        tt.simulate_tt_store(cluster, 0xBBBB, 200, False, tt.BOUND_LOWER, 20, 0x20, 60, 0)
        tt.simulate_tt_store(cluster, 0xCCCC, 300, False, tt.BOUND_LOWER, 20, 0x30, 70, 0)

        assert cluster[0]["move16"] == 0x10

        # Store new key with move=0 → evicts shallowest (slot 0, depth=5)
        tt.simulate_tt_store(cluster, 0xDDDD, 400, False, tt.BOUND_LOWER, 10, 0, 80, 0)

        assert cluster[0]["key16"] == 0xDDDD
        assert cluster[0]["move16"] == 0  # overwritten to 0 (key changed)

    def test_move_updated_when_nonzero(self):
        """Even for same key, a nonzero new move overwrites the old one."""
        cluster = [tt.empty_entry() for _ in range(3)]
        tt.simulate_tt_store(cluster, 0xBEEF, 100, False, tt.BOUND_LOWER, 10, 0x1111, 50, 0)
        tt.simulate_tt_store(cluster, 0xBEEF, 200, False, tt.BOUND_LOWER, 15, 0x2222, 60, 0)
        assert cluster[0]["move16"] == 0x2222

    def test_secondary_aging_path(self):
        """Store that fails replacement but triggers secondary aging."""
        cluster = [tt.empty_entry() for _ in range(3)]
        cluster[0]["key16"] = 0xBEEF
        cluster[0]["depth8"] = tt.encode_depth(20)  # 23
        cluster[0]["gen_bound8"] = tt.pack_gen_bound(0, tt.BOUND_LOWER, False)
        cluster[0]["move16"] = 0x1111
        cluster[0]["value"] = 31600  # decisive
        cluster[0]["eval_value"] = 0

        original_depth8 = cluster[0]["depth8"]

        # Shallow store, same key, same gen → fails all 4 replacement conditions
        # Then secondary aging fires: depth>=5, bound!=EXACT, decisive, |v|<INFINITE
        tt.simulate_tt_store(
            cluster, 0xBEEF, 500, False, tt.BOUND_LOWER,
            5, 0, 0, 0,
        )

        assert cluster[0]["depth8"] == original_depth8 - 1
        assert cluster[0]["value"] == 31600  # unchanged (replacement didn't happen)
        assert cluster[0]["move16"] == 0x1111  # move preserved

    def test_secondary_aging_blocked_by_exact_bound(self):
        """Secondary aging does not fire on BOUND_EXACT entries."""
        cluster = [tt.empty_entry() for _ in range(3)]
        cluster[0]["key16"] = 0xBEEF
        cluster[0]["depth8"] = tt.encode_depth(20)
        cluster[0]["gen_bound8"] = tt.pack_gen_bound(0, tt.BOUND_EXACT, False)
        cluster[0]["move16"] = 0x1111
        cluster[0]["value"] = 31600
        cluster[0]["eval_value"] = 0

        original_depth8 = cluster[0]["depth8"]

        tt.simulate_tt_store(
            cluster, 0xBEEF, 500, False, tt.BOUND_LOWER,
            5, 0, 0, 0,
        )

        assert cluster[0]["depth8"] == original_depth8  # unchanged

    def test_secondary_aging_blocked_nondecisive(self):
        """Secondary aging does not fire when existing value is not decisive."""
        cluster = [tt.empty_entry() for _ in range(3)]
        cluster[0]["key16"] = 0xBEEF
        cluster[0]["depth8"] = tt.encode_depth(20)
        cluster[0]["gen_bound8"] = tt.pack_gen_bound(0, tt.BOUND_LOWER, False)
        cluster[0]["move16"] = 0x1111
        cluster[0]["value"] = 100  # not decisive
        cluster[0]["eval_value"] = 0

        original_depth8 = cluster[0]["depth8"]

        tt.simulate_tt_store(
            cluster, 0xBEEF, 500, False, tt.BOUND_LOWER,
            5, 0, 0, 0,
        )

        assert cluster[0]["depth8"] == original_depth8


# ============================================================
# hashfull
# ============================================================


class TestHashfull:
    def test_all_empty(self):
        clusters = [[tt.empty_entry() for _ in range(3)] for _ in range(10)]
        assert tt.hashfull(clusters, 0, 0) == 0

    def test_fully_occupied_same_gen(self):
        clusters = []
        for _ in range(5):
            cluster = []
            for _ in range(3):
                e = tt.empty_entry()
                e["depth8"] = 10  # occupied
                e["gen_bound8"] = tt.pack_gen_bound(0, tt.BOUND_LOWER, False)
                cluster.append(e)
            clusters.append(cluster)
        # 5 clusters * 3 entries = 15 occupied, all age 0
        # hashfull = 15 // 3 = 5
        assert tt.hashfull(clusters, 0, 0) == 5

    def test_age_filtering(self):
        clusters = []
        for i in range(4):
            cluster = []
            for _ in range(3):
                e = tt.empty_entry()
                e["depth8"] = 10
                gen = 0 if i < 2 else 5
                e["gen_bound8"] = tt.pack_gen_bound(gen, tt.BOUND_LOWER, False)
                cluster.append(e)
            clusters.append(cluster)

        # At current_generation=5, max_age=0:
        # Gen 0 entries have age=5, Gen 5 entries have age=0
        # Only gen 5 entries (2 clusters × 3 = 6) counted
        assert tt.hashfull(clusters, 5, 0) == 2  # 6 // 3

        # With max_age=5: all entries counted (12 total)
        assert tt.hashfull(clusters, 5, 5) == 4  # 12 // 3

    def test_partial_occupancy(self):
        clusters = []
        for _ in range(3):
            cluster = [tt.empty_entry() for _ in range(3)]
            cluster[0]["depth8"] = 10  # only first entry occupied
            cluster[0]["gen_bound8"] = tt.pack_gen_bound(0, tt.BOUND_LOWER, False)
            clusters.append(cluster)
        # 3 occupied entries out of 9 total in 3 clusters
        assert tt.hashfull(clusters, 0, 0) == 1  # 3 // 3


# ============================================================
# TT Lifecycle — holistic multi-step interaction tests
# ============================================================


class TestTTLifecycle:
    def test_fill_cluster_and_evict(self):
        """Fill 3 entries, add 4th → shallowest evicted."""
        cluster = [tt.empty_entry() for _ in range(3)]

        tt.simulate_tt_store(cluster, 0x1111, 100, False, tt.BOUND_LOWER, 20, 0x10, 50, 0)
        tt.simulate_tt_store(cluster, 0x2222, 200, False, tt.BOUND_LOWER, 5, 0x20, 60, 0)
        tt.simulate_tt_store(cluster, 0x3333, 300, False, tt.BOUND_LOWER, 15, 0x30, 70, 0)

        keys = {e["key16"] for e in cluster}
        assert keys == {0x1111, 0x2222, 0x3333}

        # 4th store evicts shallowest (depth=5, key=0x2222)
        tt.simulate_tt_store(cluster, 0x4444, 400, False, tt.BOUND_LOWER, 10, 0x40, 80, 0)

        keys_after = {e["key16"] for e in cluster}
        assert 0x1111 in keys_after
        assert 0x3333 in keys_after
        assert 0x4444 in keys_after
        assert 0x2222 not in keys_after

    def test_generation_advancement_enables_replacement(self):
        """Stale entries are replaced even when deeper."""
        cluster = [tt.empty_entry() for _ in range(3)]

        # Deep entry at generation 0
        tt.simulate_tt_store(cluster, 0xAAAA, 100, False, tt.BOUND_LOWER, 30, 0x10, 50, 0)

        # Shallow store at same gen → fails replacement (no secondary aging: not decisive)
        tt.simulate_tt_store(cluster, 0xAAAA, 200, False, tt.BOUND_LOWER, 5, 0, 0, 0)
        assert cluster[0]["value"] == 100  # unchanged

        # At generation 3: stale entry → condition 4 fires → replacement succeeds
        tt.simulate_tt_store(cluster, 0xAAAA, 300, False, tt.BOUND_LOWER, 5, 0x55, 0, 3)
        assert cluster[0]["value"] == 300
        assert cluster[0]["depth8"] == tt.encode_depth(5)

    def test_repeated_deepening_same_key(self):
        """Storing same key with increasing depth → each update succeeds."""
        cluster = [tt.empty_entry() for _ in range(3)]

        for depth in [5, 10, 15, 20, 25]:
            tt.simulate_tt_store(
                cluster, 0xDEAD, depth * 10, False, tt.BOUND_LOWER,
                depth, 0x10, 0, 0,
            )
            hit, data, idx = tt.simulate_tt_probe(cluster, 0xDEAD, 0)
            assert hit is True
            assert data["depth"] == depth
            assert data["value"] == depth * 10

    def test_probe_after_store_returns_correct_data(self):
        """Full store→probe cycle returns consistent data."""
        cluster = [tt.empty_entry() for _ in range(3)]

        tt.simulate_tt_store(
            cluster, 0xCAFEBABE, 500, True, tt.BOUND_EXACT,
            18, 0xABCD, 250, 7,
        )

        hit, data, idx = tt.simulate_tt_probe(cluster, 0xCAFEBABE, 7)
        assert hit is True
        assert data["value"] == 500
        assert data["eval_value"] == 250
        assert data["depth"] == 18
        assert data["bound"] == tt.BOUND_EXACT
        assert data["is_pv"] is True
        assert data["move16"] == 0xABCD

    def test_exact_bound_replaces_deep_entry(self):
        """BOUND_EXACT store always overwrites regardless of depth."""
        cluster = [tt.empty_entry() for _ in range(3)]

        # Deep lower-bound entry
        tt.simulate_tt_store(cluster, 0xBEEF, 100, False, tt.BOUND_LOWER, 30, 0x10, 50, 0)
        assert cluster[0]["depth8"] == tt.encode_depth(30)

        # Shallow exact-bound store to same key → replaces (condition 1)
        tt.simulate_tt_store(cluster, 0xBEEF, 200, True, tt.BOUND_EXACT, 5, 0x20, 60, 0)
        assert cluster[0]["value"] == 200
        assert cluster[0]["depth8"] == tt.encode_depth(5)

    def test_multi_generation_eviction_sequence(self):
        """Fill cluster across multiple generations, verify age-based eviction."""
        cluster = [tt.empty_entry() for _ in range(3)]

        # Gen 0: three entries
        tt.simulate_tt_store(cluster, 0x1111, 100, False, tt.BOUND_LOWER, 10, 0x10, 50, 0)
        tt.simulate_tt_store(cluster, 0x2222, 200, False, tt.BOUND_LOWER, 10, 0x20, 60, 0)
        tt.simulate_tt_store(cluster, 0x3333, 300, False, tt.BOUND_LOWER, 10, 0x30, 70, 0)

        # Gen 5: store to first entry (update it to new generation)
        tt.simulate_tt_store(cluster, 0x1111, 150, False, tt.BOUND_LOWER, 10, 0x15, 55, 5)

        # Gen 5: new entry → should evict a stale gen-0 entry (not 0x1111 which is now gen 5)
        tt.simulate_tt_store(cluster, 0x4444, 400, False, tt.BOUND_LOWER, 10, 0x40, 80, 5)

        keys = {e["key16"] for e in cluster}
        assert 0x1111 in keys  # kept (updated to gen 5)
        assert 0x4444 in keys  # new entry
        # One of 0x2222 or 0x3333 was evicted (both are stale gen 0)

    def test_hashfull_after_stores(self):
        """hashfull correctly reflects occupation after simulated stores."""
        clusters = [[tt.empty_entry() for _ in range(3)] for _ in range(5)]

        # Store into first 3 clusters
        for i in range(3):
            key = 0x1000 + i
            tt.simulate_tt_store(clusters[i], key, 100, False, tt.BOUND_LOWER, 10, 0, 0, 0)

        # 3 occupied entries across 5 clusters
        assert tt.hashfull(clusters, 0, 0) == 1  # 3 // 3
