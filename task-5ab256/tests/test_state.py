"""
Tests for microcode ROM reverse engineering task.

Verifies that /app/answers.json contains correct results and that
the DOT/SVG control flow graph outputs are produced correctly.

"""

import json
import os
import re
import pytest


# -- Expected answers (computed from the generation script) --

EXPECTED_PERMUTATION = [17, 3, 11, 23, 7, 14, 0, 20, 9, 22, 5, 13, 1, 19, 8, 16, 12, 4, 21, 6, 15, 2, 10, 18]

EXPECTED_DECODED_WORDS = {
    "10": "0x000089",
    "25": "0x000086",
    "49": "0x164FCC",
    "75": "0x000038",
    "100": "0x000A66",
}

EXPECTED_END_COUNT = 46

EXPECTED_ALU_HISTOGRAM = {
    "MOV": 64,
    "ADD": 12,
    "SUB": 5,
    "AND": 3,
    "OR": 2,
    "XOR": 3,
    "SHL": 3,
    "SHR": 3,
    "CMP": 3,
    "INC": 8,
    "DEC": 7,
    "NOT": 2,
    "NEG": 2,
    "TEST": 1,
    "ADC": 2,
    "NOP": 8,
}

EXPECTED_BUG = {
    "address": 49,
    "field": "imm",
    "actual_value": 44,
    "correct_value": 43,
}

EXPECTED_UNIQUE_REGISTER_PAIRS = 54

EXPECTED_CFG_EDGE_COUNT = 86


@pytest.fixture
def answers():
    answers_path = "/app/answers.json"
    assert os.path.exists(answers_path), f"answers.json not found at {answers_path}"
    with open(answers_path) as f:
        return json.load(f)


class TestPermutation:
    def test_permutation_exists(self, answers):
        assert "permutation" in answers, "Missing 'permutation' key"

    def test_permutation_is_valid(self, answers):
        perm = answers["permutation"]
        assert isinstance(perm, list), "permutation must be a list"
        assert len(perm) == 24, f"permutation must have 24 elements, got {len(perm)}"
        assert sorted(perm) == list(range(24)), "permutation must be a valid permutation of 0..23"

    def test_permutation_correct(self, answers):
        perm = answers["permutation"]
        assert perm == EXPECTED_PERMUTATION, (
            f"Permutation mismatch.\n"
            f"Expected: {EXPECTED_PERMUTATION}\n"
            f"Got:      {perm}"
        )


class TestDecodedWords:
    def test_decoded_words_exists(self, answers):
        assert "decoded_words" in answers, "Missing 'decoded_words' key"

    def test_decoded_words_complete(self, answers):
        words = answers["decoded_words"]
        for addr in ["10", "25", "49", "75", "100"]:
            assert addr in words, f"Missing decoded word for address {addr}"

    @pytest.mark.parametrize("addr", ["10", "25", "49", "75", "100"])
    def test_decoded_word_correct(self, answers, addr):
        actual = answers["decoded_words"][addr]
        expected = EXPECTED_DECODED_WORDS[addr]
        actual_int = int(actual, 16)
        expected_int = int(expected, 16)
        assert actual_int == expected_int, (
            f"Decoded word at addr {addr}: expected {expected} (0x{expected_int:06X}), "
            f"got {actual} (0x{actual_int:06X})"
        )


class TestEndCount:
    def test_end_count_exists(self, answers):
        assert "end_count" in answers, "Missing 'end_count' key"

    def test_end_count_correct(self, answers):
        assert answers["end_count"] == EXPECTED_END_COUNT, (
            f"END count: expected {EXPECTED_END_COUNT}, got {answers['end_count']}"
        )


class TestAluHistogram:
    def test_histogram_exists(self, answers):
        assert "alu_histogram" in answers, "Missing 'alu_histogram' key"

    def test_histogram_complete(self, answers):
        hist = answers["alu_histogram"]
        for op_name in EXPECTED_ALU_HISTOGRAM:
            assert op_name in hist, f"Missing ALU operation '{op_name}' in histogram"

    @pytest.mark.parametrize("op_name,expected_count", list(EXPECTED_ALU_HISTOGRAM.items()))
    def test_histogram_value(self, answers, op_name, expected_count):
        hist = answers["alu_histogram"]
        actual = hist.get(op_name, 0)
        assert actual == expected_count, (
            f"ALU histogram['{op_name}']: expected {expected_count}, got {actual}"
        )


class TestBug:
    def test_bug_exists(self, answers):
        assert "bug" in answers, "Missing 'bug' key"

    def test_bug_address(self, answers):
        bug = answers["bug"]
        assert bug.get("address") == EXPECTED_BUG["address"], (
            f"Bug address: expected {EXPECTED_BUG['address']}, got {bug.get('address')}"
        )

    def test_bug_field(self, answers):
        bug = answers["bug"]
        assert bug.get("field") == EXPECTED_BUG["field"], (
            f"Bug field: expected '{EXPECTED_BUG['field']}', got '{bug.get('field')}'"
        )

    def test_bug_actual_value(self, answers):
        bug = answers["bug"]
        assert bug.get("actual_value") == EXPECTED_BUG["actual_value"], (
            f"Bug actual_value: expected {EXPECTED_BUG['actual_value']}, got {bug.get('actual_value')}"
        )

    def test_bug_correct_value(self, answers):
        bug = answers["bug"]
        assert bug.get("correct_value") == EXPECTED_BUG["correct_value"], (
            f"Bug correct_value: expected {EXPECTED_BUG['correct_value']}, got {bug.get('correct_value')}"
        )


class TestUniqueRegisterPairs:
    def test_pairs_exists(self, answers):
        assert "unique_register_pairs" in answers, "Missing 'unique_register_pairs' key"

    def test_pairs_correct(self, answers):
        assert answers["unique_register_pairs"] == EXPECTED_UNIQUE_REGISTER_PAIRS, (
            f"Unique register pairs: expected {EXPECTED_UNIQUE_REGISTER_PAIRS}, "
            f"got {answers['unique_register_pairs']}"
        )


class TestCfgEdgeCount:
    def test_cfg_edge_count_exists(self, answers):
        assert "cfg_edge_count" in answers, "Missing 'cfg_edge_count' key"

    def test_cfg_edge_count_correct(self, answers):
        assert answers["cfg_edge_count"] == EXPECTED_CFG_EDGE_COUNT, (
            f"CFG edge count: expected {EXPECTED_CFG_EDGE_COUNT}, "
            f"got {answers['cfg_edge_count']}"
        )


class TestControlFlowGraph:
    def test_dot_file_exists(self):
        assert os.path.exists("/app/microcode_cfg.dot"), "microcode_cfg.dot not found"

    def test_dot_is_valid_digraph(self):
        with open("/app/microcode_cfg.dot") as f:
            content = f.read()
        assert "digraph" in content, "DOT file must contain 'digraph' keyword"

    def test_dot_has_subgraphs(self):
        with open("/app/microcode_cfg.dot") as f:
            content = f.read()
        assert "subgraph" in content, "DOT file must contain subgraph clusters"

    def test_dot_has_correct_edge_count(self):
        with open("/app/microcode_cfg.dot") as f:
            content = f.read()
        edge_count = content.count("->")
        assert edge_count == EXPECTED_CFG_EDGE_COUNT, (
            f"DOT file edge count: expected {EXPECTED_CFG_EDGE_COUNT}, found {edge_count}"
        )

    def test_dot_has_buggy_edge(self):
        with open("/app/microcode_cfg.dot") as f:
            content = f.read()
        # The buggy JMP at addr 49 targets addr 44
        assert re.search(r'[n"]?49["]?\s*->\s*[n"]?44["]?', content), (
            "Missing edge from addr 49 to addr 44 (buggy JMP target)"
        )

    def test_svg_file_exists(self):
        assert os.path.exists("/app/microcode_cfg.svg"), "microcode_cfg.svg not found"

    def test_svg_is_valid(self):
        with open("/app/microcode_cfg.svg") as f:
            content = f.read()
        assert "<svg" in content, "SVG file does not contain <svg tag"

    def test_svg_has_content(self):
        size = os.path.getsize("/app/microcode_cfg.svg")
        assert size > 1000, f"SVG file too small ({size} bytes), expected substantial graph"
