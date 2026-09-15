"""Tests for logminer.chunker module."""
import signal


def test_single_chunk():
    """Short text fits in one chunk."""
    from logminer.chunker import split_with_overlap
    text = "line1\nline2\nline3"
    chunks = split_with_overlap(text, chunk_size=10)
    assert len(chunks) == 1
    assert chunks[0] == (1, 3, text)


def test_multiple_chunks():
    """Long text is correctly split into overlapping chunks."""
    from logminer.chunker import split_with_overlap
    lines = [f"line{i}" for i in range(20)]
    text = '\n'.join(lines)
    chunks = split_with_overlap(text, chunk_size=8, overlap=2)
    assert len(chunks) > 1
    # Verify all original lines appear in at least one chunk
    all_lines_covered = set()
    for start, end, chunk_text in chunks:
        for line in chunk_text.split('\n'):
            all_lines_covered.add(line)
    for line in lines:
        assert line in all_lines_covered, f"Line {line!r} missing from chunks"


def test_overlap_exceeds_chunk_size():
    """When overlap >= chunk_size, must not enter infinite loop."""
    from logminer.chunker import split_with_overlap

    def timeout_handler(signum, frame):
        raise TimeoutError("Infinite loop detected")

    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(5)  # 5 second timeout
    try:
        result = split_with_overlap(
            "a\nb\nc\nd\ne\nf\ng\nh\ni\nj",
            chunk_size=2,
            overlap=3,
        )
        assert isinstance(result, list)
        assert len(result) > 0
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def test_empty_input():
    """Empty string returns empty list."""
    from logminer.chunker import split_with_overlap
    result = split_with_overlap("")
    assert isinstance(result, list)
    assert len(result) == 0
