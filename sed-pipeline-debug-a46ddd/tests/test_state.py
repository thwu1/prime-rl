"""Tests for the sed-based text processing pipeline at /app/transform.sh.

The pipeline joins continuation lines, removes consecutive duplicates,
folds consecutive tagged entries, and numbers each output line with a
zero-padded 3-digit sequence number.
"""


import subprocess
import pytest


def run_transform(input_text: str) -> tuple[str, str, int]:
    """Run /app/transform.sh with the given input on stdin."""
    result = subprocess.run(
        ["/bin/bash", "/app/transform.sh"],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout, result.stderr, result.returncode


def reference_transform(input_text: str) -> str:
    """Python reference implementation of the four-phase pipeline."""
    lines = input_text.rstrip("\n").split("\n")
    if lines == [""]:
        return ""

    # Phase 1: Join continuation lines (lines starting with "> ")
    joined: list[str] = []
    for line in lines:
        if line.startswith("> ") and joined:
            joined[-1] = joined[-1] + " " + line[2:]
        else:
            joined.append(line)

    # Phase 2: Remove consecutive duplicates (like uniq)
    deduped: list[str] = []
    for line in joined:
        if not deduped or deduped[-1] != line:
            deduped.append(line)

    # Phase 3: Fold consecutive lines sharing same tag prefix
    folded: list[str] = []
    i = 0
    while i < len(deduped):
        line = deduped[i]
        if ":" not in line:
            folded.append(line)
            i += 1
            continue
        tag = line.split(":", 1)[0]
        base = line
        j = i + 1
        while (
            j < len(deduped)
            and ":" in deduped[j]
            and deduped[j].split(":", 1)[0] == tag
        ):
            value = deduped[j].split(":", 1)[1].lstrip(" ")
            base = base + " | " + value
            j += 1
        folded.append(base)
        i = j

    # Phase 4: Number each line with [NNN] prefix
    numbered = [f"[{i:03d}] {line}" for i, line in enumerate(folded, 1)]
    return "\n".join(numbered) + "\n"


# ---------------------------------------------------------------------------
# Basic functionality
# ---------------------------------------------------------------------------

class TestBasicPipeline:
    """Tests for basic pipeline operation."""

    def test_simple_lines(self):
        """Simple lines with no continuations, duplicates, or tags."""
        inp = "alpha\nbeta\ngamma\n"
        stdout, _, rc = run_transform(inp)
        assert stdout == reference_transform(inp)
        assert rc == 0

    def test_single_line(self):
        """Single-line input."""
        inp = "only line\n"
        stdout, _, _ = run_transform(inp)
        assert stdout.strip() == "[001] only line"

    def test_exit_code_zero(self):
        """Tool exits with code 0 on valid input."""
        _, _, rc = run_transform("test\n")
        assert rc == 0


# ---------------------------------------------------------------------------
# Phase 1: Continuation line joining
# ---------------------------------------------------------------------------

class TestContinuationJoining:
    """Tests for the join phase (lines starting with '> ')."""

    def test_single_continuation(self):
        """One continuation line joins to its predecessor."""
        inp = "base line\n> continued here\nnext line\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_multiple_continuations(self):
        """Multiple consecutive continuations all join to the same base."""
        inp = "header\n> part two\n> part three\n> part four\nfooter\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_continuation_at_third_position(self):
        """Continuation following a non-first line must join correctly."""
        inp = "alpha\nbeta\n> gamma\ndelta\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_continuation_as_last_line(self):
        """A continuation as the very last line must still be joined."""
        inp = "base line\n> final part\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_continuation_at_start_of_input(self):
        """A '> ' line at the very start has nothing to join to."""
        inp = "> orphan line\nnormal line\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_no_false_continuation(self):
        """Lines that do not start with '> ' are never joined."""
        inp = "first\nsecond\nthird\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)


# ---------------------------------------------------------------------------
# Phase 2: Consecutive duplicate removal
# ---------------------------------------------------------------------------

class TestDuplicateRemoval:
    """Tests for the dedup phase (consecutive identical lines collapsed)."""

    def test_consecutive_duplicates(self):
        """Runs of identical lines collapse to one."""
        inp = "aaa\naaa\naaa\nbbb\nbbb\nccc\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_non_consecutive_duplicates_preserved(self):
        """Identical lines that are NOT consecutive must both appear."""
        inp = "aaa\nbbb\naaa\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_prefix_is_not_duplicate(self):
        """A line that is a prefix of the next line is NOT a duplicate."""
        inp = "foo\nfoobar\nfoo\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_blank_lines_deduplication(self):
        """Multiple consecutive blank lines collapse to one."""
        inp = "line one\n\n\n\nline two\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_all_identical(self):
        """Input of all identical lines produces a single numbered line."""
        inp = "same\nsame\nsame\nsame\n"
        stdout, _, _ = run_transform(inp)
        assert stdout.strip() == "[001] same"


# ---------------------------------------------------------------------------
# Phase 3: Record folding
# ---------------------------------------------------------------------------

class TestRecordFolding:
    """Tests for the fold phase (consecutive same-tag entries combined)."""

    def test_two_same_tag(self):
        """Two consecutive lines with the same tag fold into one."""
        inp = "TAG: alpha\nTAG: beta\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)
        assert "TAG: alpha | beta" in stdout

    def test_three_same_tag(self):
        """Three consecutive same-tag lines fold into one."""
        inp = "X: one\nX: two\nX: three\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)
        assert "X: one | two | three" in stdout

    def test_different_tags_no_fold(self):
        """Consecutive lines with different tags are NOT folded."""
        inp = "A: first\nB: second\nC: third\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)
        lines = stdout.strip().split("\n")
        assert len(lines) == 3

    def test_no_colon_passthrough(self):
        """Lines without a colon pass through and break fold groups."""
        inp = "TAG: one\nplain line\nTAG: two\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)
        lines = stdout.strip().split("\n")
        assert len(lines) == 3

    def test_single_entry_group(self):
        """A lone tagged line (no same-tag neighbor) passes unchanged."""
        inp = "SOLO: value\nother stuff\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_fold_at_end_of_input(self):
        """Fold group at the very end of input is handled correctly."""
        inp = "preamble\nK: last1\nK: last2\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)
        assert "K: last1 | last2" in stdout

    def test_value_contains_colon(self):
        """Tag is only the text before the FIRST colon; values may have colons."""
        inp = "NET: host:port=8080\nNET: host:port=9090\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)
        assert "NET: host:port=8080 | host:port=9090" in stdout

    def test_mixed_tagged_and_plain(self):
        """Complex interleaving of tagged groups and plain lines."""
        inp = (
            "plain1\n"
            "ERR: e1\n"
            "ERR: e2\n"
            "plain2\n"
            "INFO: i1\n"
            "INFO: i2\n"
            "INFO: i3\n"
            "plain3\n"
        )
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)
        lines = stdout.strip().split("\n")
        assert len(lines) == 5

    def test_similar_tag_prefixes_no_cross_fold(self):
        """Tags that share a prefix but differ must not fold together."""
        inp = "ERR: one\nERROR: two\nERROR: three\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)
        lines = stdout.strip().split("\n")
        assert len(lines) == 2  # ERR alone + ERROR folded


# ---------------------------------------------------------------------------
# Phase 4: Sequential line numbering
# ---------------------------------------------------------------------------

class TestLineNumbering:
    """Tests for the numbering phase ([NNN] prefix)."""

    def test_starts_at_001(self):
        """Numbering must start at 001, not 000."""
        stdout, _, _ = run_transform("first\n")
        assert stdout.startswith("[001] ")

    def test_increments_correctly(self):
        """Each successive line has the next number."""
        stdout, _, _ = run_transform("a\nb\nc\n")
        lines = stdout.strip().split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("[001]")
        assert lines[1].startswith("[002]")
        assert lines[2].startswith("[003]")

    def test_format_bracket_number_space(self):
        """Output format is exactly '[NNN] line_content'."""
        stdout, _, _ = run_transform("hello world\n")
        assert stdout.strip() == "[001] hello world"

    def test_no_extra_output_lines(self):
        """No counter values or other debris should leak into output."""
        stdout, _, _ = run_transform("a\nb\nc\n")
        lines = stdout.strip().split("\n")
        assert len(lines) == 3

    def test_carry_9_to_10(self):
        """Carry propagation at the 9 -> 10 boundary."""
        inp = "\n".join(f"line {i}" for i in range(1, 12)) + "\n"
        stdout, _, _ = run_transform(inp)
        output_lines = stdout.strip().split("\n")
        assert output_lines[8].startswith("[009]")
        assert output_lines[9].startswith("[010]")
        assert output_lines[10].startswith("[011]")

    def test_carry_99_to_100(self):
        """Carry propagation at the 99 -> 100 boundary."""
        inp = "\n".join(f"line {i}" for i in range(1, 102)) + "\n"
        stdout, _, _ = run_transform(inp)
        output_lines = stdout.strip().split("\n")
        assert output_lines[98].startswith("[099]")
        assert output_lines[99].startswith("[100]")
        assert output_lines[100].startswith("[101]")

    def test_twenty_lines(self):
        """Correct numbering for 20 lines."""
        lines = [f"line {i}" for i in range(1, 21)]
        inp = "\n".join(lines) + "\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)


# ---------------------------------------------------------------------------
# Combined / integration
# ---------------------------------------------------------------------------

class TestIntegration:
    """Tests exercising multiple phases together."""

    def test_combined_all_phases(self):
        """Continuations + duplicates + fold + numbering together."""
        inp = (
            "start\n"
            "start\n"
            "LOG: msg1\n"
            "> continued\n"
            "LOG: msg1 continued\n"
            "LOG: msg2\n"
            "end\n"
        )
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_dedup_before_fold(self):
        """Duplicate tagged lines must be deduplicated before folding.

        With correct pipeline order (dedup then fold):
          TAG: apple, TAG: apple, TAG: banana
          -> dedup -> TAG: apple, TAG: banana
          -> fold  -> TAG: apple | banana

        With wrong order (fold then dedup):
          -> fold  -> TAG: apple | apple | banana
          -> dedup -> TAG: apple | apple | banana (no consecutive dup)
        """
        inp = "TAG: apple\nTAG: apple\nTAG: banana\n"
        stdout, _, _ = run_transform(inp)
        expected = reference_transform(inp)
        assert stdout == expected
        assert "apple | banana" in stdout
        assert "apple | apple" not in stdout

    def test_last_line_not_lost(self):
        """The last line of input must appear in output."""
        inp = "first\nsecond\nthird\n"
        stdout, _, _ = run_transform(inp)
        assert "third" in stdout

    def test_odd_line_count(self):
        """Odd number of input lines are all preserved."""
        inp = "a\nb\nc\nd\ne\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_even_line_count(self):
        """Even number of input lines are all preserved."""
        inp = "a\nb\nc\nd\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_sample_input(self):
        """The sample_input.txt file is processed correctly."""
        with open("/app/sample_input.txt") as f:
            inp = f.read()
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_complex_scenario(self):
        """Complex input exercising all edge cases together."""
        inp = (
            "first entry\n"
            "> with continuation\n"
            "second entry\n"
            "second entry\n"
            "SVC: alpha\n"
            "SVC: beta\n"
            "> extended\n"
            "SVC: beta extended\n"
            "SVC: gamma\n"
            "prefix\n"
            "prefix extended\n"
            "DB: conn1\n"
            "final entry\n"
        )
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)

    def test_fold_group_after_continuation_and_dedup(self):
        """Continuations create duplicate tagged lines that dedup before fold."""
        inp = (
            "STAT: ok\n"
            "> indeed\n"
            "STAT: ok indeed\n"
            "STAT: fail\n"
        )
        stdout, _, _ = run_transform(inp)
        expected = reference_transform(inp)
        assert stdout == expected
        # After join: STAT: ok indeed, STAT: ok indeed, STAT: fail
        # After dedup: STAT: ok indeed, STAT: fail
        # After fold: STAT: ok indeed | fail
        assert "STAT: ok indeed | fail" in stdout

    def test_large_fold_group(self):
        """A fold group with many entries (5+) is handled correctly."""
        inp = "\n".join(f"LOG: entry{i}" for i in range(1, 8)) + "\n"
        stdout, _, _ = run_transform(inp)
        assert stdout == reference_transform(inp)
        assert stdout.count("|") == 6  # 7 entries joined by 6 pipes

    def test_no_tools_besides_sed(self):
        """transform.sh must not invoke non-sed tools in the pipeline."""
        with open("/app/transform.sh") as f:
            content = f.read()
        for tool in ["awk", "perl", "python", "tr ", "cut ", "paste "]:
            assert tool not in content, f"Pipeline must not use {tool.strip()}"
