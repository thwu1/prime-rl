
import pytest
import sys
import time
import sqlite3
import json
import subprocess

sys.path.insert(0, "/app")

from tokenizer import BPETokenizer


@pytest.fixture(scope="module")
def tok():
    t = BPETokenizer()
    t.load("/app/model.bin")
    return t


@pytest.fixture(scope="module")
def db():
    conn = sqlite3.connect("/app/tokenizer.db")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ===========================================================================
# Roundtrip: decode(optimal_encode(text)) == text
# ===========================================================================

@pytest.mark.parametrize("text", [
    "",
    "a",
    "z",
    "hello",
    "world",
    "the",
    "there",
    "pqrs",
    "{|}",
    "JKLM",
    "#$%&'",
    ":;<=>?@",
    "hello world",
    "the quick brown fox",
    "in the JKLM",
    "testing 123",
    "aaabdaaabac",
    "   ",
    "aeiou",
    "pqrspqrs",
    "therethe",
])
def test_roundtrip(tok, text):
    ids = tok.optimal_encode(text)
    assert isinstance(ids, list), "optimal_encode must return a list"
    assert all(isinstance(x, int) for x in ids), "All IDs must be ints"
    decoded = tok.decode(ids)
    assert decoded == text, f"Roundtrip failed: {text!r} -> {ids} -> {decoded!r}"


# ===========================================================================
# optimal <= greedy for every input
# ===========================================================================

@pytest.mark.parametrize("text", [
    "hello",
    "the",
    "pqrs",
    "{|}",
    "JKLM",
    "#$%&'",
    ":;<=>?@",
    "in the JKLM",
    "the quick brown fox",
    "testing",
    "information",
    "pqrspqrs",
    "there in the #$%&' or :;<=>?@",
])
def test_optimal_leq_greedy(tok, text):
    g = tok.greedy_encode(text)
    o = tok.optimal_encode(text)
    assert len(o) <= len(g), (
        f"Optimal ({len(o)}) > greedy ({len(g)}) for {text!r}"
    )


# ===========================================================================
# Trap strings: exact greedy and optimal token counts
# ===========================================================================

def test_trap_pqrs(tok):
    """pq(rank20) + rs(rank21) block the qr(22)->pqr(23)->pqrs(24) chain."""
    g = tok.greedy_encode("pqrs")
    o = tok.optimal_encode("pqrs")
    assert len(g) == 2, f"Greedy 'pqrs': expected 2, got {len(g)}: {g}"
    assert len(o) == 1, f"Optimal 'pqrs': expected 1, got {len(o)}: {o}"
    assert tok.decode(o) == "pqrs"


def test_trap_braces(tok):
    """{|(rank31) blocks |}->{|} chain."""
    g = tok.greedy_encode("{|}")
    o = tok.optimal_encode("{|}")
    assert len(g) == 2, f"Greedy '{{|}}': expected 2, got {len(g)}: {g}"
    assert len(o) == 1, f"Optimal '{{|}}': expected 1, got {len(o)}: {o}"
    assert tok.decode(o) == "{|}"


def test_trap_JKLM(tok):
    """JK(rank34) + LM(rank35) block KL(36)->JKL(37)->JKLM(38) chain."""
    g = tok.greedy_encode("JKLM")
    o = tok.optimal_encode("JKLM")
    assert len(g) == 2, f"Greedy 'JKLM': expected 2, got {len(g)}: {g}"
    assert len(o) == 1, f"Optimal 'JKLM': expected 1, got {len(o)}: {o}"
    assert tok.decode(o) == "JKLM"


def test_trap_symbols(tok):
    """#$(rank25) + %&(rank26) block the $%->...->#$%&' chain."""
    g = tok.greedy_encode("#$%&'")
    o = tok.optimal_encode("#$%&'")
    assert len(g) == 3, f"Greedy '#$%&\\'': expected 3, got {len(g)}: {g}"
    assert len(o) == 1, f"Optimal '#$%&\\'': expected 1, got {len(o)}: {o}"
    assert tok.decode(o) == "#$%&'"


def test_trap_punct(tok):
    """:;(39) <=(40) >?(41) block the ;< chain to :;<=>?@."""
    g = tok.greedy_encode(":;<=>?@")
    o = tok.optimal_encode(":;<=>?@")
    assert len(g) == 4, f"Greedy ':;<=>?@': expected 4, got {len(g)}: {g}"
    assert len(o) == 1, f"Optimal ':;<=>?@': expected 1, got {len(o)}: {o}"
    assert tok.decode(o) == ":;<=>?@"


def test_natural_trap_in_the(tok):
    """'e '(rank0) blocks ' the '(rank7) token; JK+LM block JKLM."""
    g = tok.greedy_encode("in the JKLM")
    o = tok.optimal_encode("in the JKLM")
    assert len(g) == 5, f"Greedy 'in the JKLM': expected 5, got {len(g)}: {g}"
    assert len(o) == 3, f"Optimal 'in the JKLM': expected 3, got {len(o)}: {o}"
    assert tok.decode(o) == "in the JKLM"


# ===========================================================================
# compression_gap
# ===========================================================================

def test_gap_zero(tok):
    assert tok.compression_gap("hello") == 0


def test_gap_pqrs(tok):
    assert tok.compression_gap("pqrs") == 1


def test_gap_symbols(tok):
    assert tok.compression_gap("#$%&'") == 2


def test_gap_punct(tok):
    assert tok.compression_gap(":;<=>?@") == 3


def test_gap_in_the_JKLM(tok):
    assert tok.compression_gap("in the JKLM") == 2


# ===========================================================================
# count_optimal_tokenizations
# ===========================================================================

def test_count_empty(tok):
    assert tok.count_optimal_tokenizations("") == 1


def test_count_single(tok):
    assert tok.count_optimal_tokenizations("a") == 1


def test_count_pqrs(tok):
    """Only [pqrs] achieves 1 token."""
    assert tok.count_optimal_tokenizations("pqrs") == 1


def test_count_the(tok):
    """Two optimal: [th][e] and [t][he]."""
    assert tok.count_optimal_tokenizations("the") == 2


def test_count_qrs(tok):
    """Two optimal of length 2: [qr][s] and [q][rs]."""
    assert tok.count_optimal_tokenizations("qrs") == 2


def test_count_KLM(tok):
    """Two optimal of length 2: [KL][M] and [K][LM]."""
    assert tok.count_optimal_tokenizations("KLM") == 2


def test_count_there(tok):
    """Three optimal of length 3: [th][er][e], [t][he][re], [th][e][re]."""
    assert tok.count_optimal_tokenizations("there") == 3


def test_count_therethe(tok):
    """Independent sub-problems: 3 ways for 'there' * 2 ways for 'the' = 6."""
    assert tok.count_optimal_tokenizations("therethe") == 6


# ===========================================================================
# Independent DP verification on compound strings
# ===========================================================================

def _independent_min_tokens(tok, text):
    """Reference DP — completely independent of the agent's implementation."""
    data = text.encode("utf-8")
    n = len(data)
    if n == 0:
        return 0
    tset = set()
    for idx, bseq in tok.vocab.items():
        tset.add(bseq)
    mtl = max(len(s) for s in tset) if tset else 1
    INF = float("inf")
    dp = [INF] * (n + 1)
    dp[0] = 0
    for i in range(1, n + 1):
        for length in range(1, min(i, mtl) + 1):
            if bytes(data[i - length : i]) in tset and dp[i - length] + 1 < dp[i]:
                dp[i] = dp[i - length] + 1
    return dp[n]


@pytest.mark.parametrize("text", [
    "hello world",
    "pqrs JKLM",
    "there in the #$%&' or :;<=>?@",
    "the the the",
    "and then there",
    "pqrs{|}JKLM#$%&':;<=>?@",
    "in the and the tion or ing",
])
def test_independent_verification(tok, text):
    expected = _independent_min_tokens(tok, text)
    actual = tok.optimal_encode(text)
    assert len(actual) == expected, (
        f"For {text!r}: expected min {expected}, got {len(actual)}"
    )
    assert tok.decode(actual) == text


# ===========================================================================
# Token validity: every ID in the output must be in the vocabulary
# ===========================================================================

@pytest.mark.parametrize("text", [
    "hello",
    "pqrs",
    ":;<=>?@",
    "in the JKLM",
    "#$%&'",
])
def test_tokens_in_vocab(tok, text):
    ids = tok.optimal_encode(text)
    for tid in ids:
        assert tid in tok.vocab, f"Token ID {tid} not in vocabulary"


# ===========================================================================
# Performance: optimal_encode on ~10 KB must finish within 30 seconds
# ===========================================================================

def test_performance(tok):
    long_text = (
        "the quick brown fox jumps over the lazy dog and the pqrs " * 200
    )
    start = time.time()
    result = tok.optimal_encode(long_text)
    elapsed = time.time() - start
    assert elapsed < 30, f"optimal_encode took {elapsed:.1f}s, limit is 30s"
    assert tok.decode(result) == long_text
    greedy_result = tok.greedy_encode(long_text)
    assert len(result) <= len(greedy_result)


# ===========================================================================
# Greedy encoding must match compiled binary reference
# ===========================================================================

@pytest.mark.parametrize("text", [
    "hello",
    "pqrs",
    "JKLM",
    "{|}",
    "#$%&'",
    ":;<=>?@",
    "in the JKLM",
    "world",
    "the",
    "there",
    "testing 123",
])
def test_greedy_matches_binary(tok, text):
    """Greedy encoding must produce identical output to the compiled encoder."""
    result = subprocess.run(
        ["/app/bpe_encoder", "/app/model.bin", "encode", text],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, f"Binary encoder failed: {result.stderr}"
    expected_ids = list(map(int, result.stdout.strip().split()))
    actual_ids = tok.greedy_encode(text)
    assert actual_ids == expected_ids, (
        f"Greedy mismatch for {text!r}: got {actual_ids}, binary says {expected_ids}"
    )


# ===========================================================================
# SQLite database: merges table
# ===========================================================================

def test_db_merges_count(db):
    cur = db.execute("SELECT COUNT(*) FROM merges")
    assert cur.fetchone()[0] == 50, "Expected 50 merges in database"


def test_db_merges_rank0(db):
    cur = db.execute(
        "SELECT parent0, parent1, merged_id, merged_bytes_hex "
        "FROM merges WHERE rank = 0"
    )
    row = cur.fetchone()
    assert row is not None, "Missing rank 0 merge"
    assert (row["parent0"], row["parent1"], row["merged_id"]) == (101, 32, 256)
    assert row["merged_bytes_hex"] == "6520"


def test_db_merges_rank24(db):
    """pqrs token merge."""
    cur = db.execute(
        "SELECT parent0, parent1, merged_id, merged_bytes_hex "
        "FROM merges WHERE rank = 24"
    )
    row = cur.fetchone()
    assert row is not None, "Missing rank 24 merge"
    assert row["merged_id"] == 280
    assert row["merged_bytes_hex"] == "70717273"


def test_db_merges_rank33(db):
    """{|} token merge."""
    cur = db.execute(
        "SELECT merged_bytes_hex FROM merges WHERE rank = 33"
    )
    row = cur.fetchone()
    assert row is not None, "Missing rank 33 merge"
    assert row["merged_bytes_hex"] == "7b7c7d"


# ===========================================================================
# SQLite database: encodings table
# ===========================================================================

def test_db_encodings_count(db):
    cur = db.execute("SELECT COUNT(*) FROM encodings")
    assert cur.fetchone()[0] == 8, "Expected 8 encoding entries"


def test_db_encodings_pqrs(db):
    cur = db.execute(
        "SELECT greedy_count, optimal_count, gap "
        "FROM encodings WHERE input_text = 'pqrs'"
    )
    row = cur.fetchone()
    assert row is not None, "Missing encoding for 'pqrs'"
    assert row["greedy_count"] == 2
    assert row["optimal_count"] == 1
    assert row["gap"] == 1


def test_db_encodings_all_gaps(db):
    expected = {
        "hello": 0, "world": 0, "pqrs": 1, "{|}": 1,
        "JKLM": 1, "#$%&'": 2, ":;<=>?@": 3, "in the JKLM": 2,
    }
    for text, exp_gap in expected.items():
        cur = db.execute(
            "SELECT gap FROM encodings WHERE input_text = ?", (text,)
        )
        row = cur.fetchone()
        assert row is not None, f"Missing encoding for {text!r}"
        assert row["gap"] == exp_gap, (
            f"Wrong gap for {text!r}: expected {exp_gap}, got {row['gap']}"
        )


def test_db_encodings_valid_json(db):
    cur = db.execute("SELECT input_text, greedy_ids, optimal_ids FROM encodings")
    for row in cur.fetchall():
        g = json.loads(row["greedy_ids"])
        o = json.loads(row["optimal_ids"])
        assert isinstance(g, list), f"greedy_ids not a list for {row['input_text']}"
        assert isinstance(o, list), f"optimal_ids not a list for {row['input_text']}"
        assert all(isinstance(x, int) for x in g)
        assert all(isinstance(x, int) for x in o)
