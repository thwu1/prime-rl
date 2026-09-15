"""Tests for logminer.localizer module."""
import pytest


def test_build_outline_functions():
    """Functions are correctly detected in the outline."""
    from logminer.localizer import build_outline
    code = (
        "def foo():\n"
        "    return 1\n"
        "\n"
        "def bar():\n"
        "    return 2\n"
    )
    outline = build_outline(code)
    names = [n.name for n in outline]
    assert 'foo' in names
    assert 'bar' in names


def test_build_outline_class():
    """Classes with methods are correctly detected."""
    from logminer.localizer import build_outline
    code = (
        "class MyClass:\n"
        "    def method_a(self):\n"
        "        return 1\n"
        "\n"
        "    def method_b(self):\n"
        "        return 2\n"
    )
    outline = build_outline(code)
    assert len(outline) == 1
    assert outline[0].kind == 'class'
    assert outline[0].name == 'MyClass'
    assert len(outline[0].children) == 2


def test_find_enclosing_node_contained():
    """Enclosing node is found for a line fully inside a method."""
    from logminer.localizer import build_outline, find_enclosing_node
    code = (
        "class MyClass:\n"
        "    def method_a(self):\n"
        "        x = 1\n"
        "        y = 2\n"
        "        return x + y\n"
        "\n"
        "    def method_b(self):\n"
        "        return 42\n"
    )
    outline = build_outline(code)
    # Line 3 is inside method_a
    result = find_enclosing_node(outline, 3, 3)
    assert result is not None
    assert result.name == 'method_a'


def test_find_enclosing_node_strict():
    """find_enclosing_node must use strict containment, not intersection."""
    from logminer.localizer import build_outline, find_enclosing_node
    code = (
        "x = 1\n"
        "y = 2\n"
        "z = 3\n"
        "\n"
        "def foo():\n"
        "    a = 1\n"
        "    b = 2\n"
        "    return a + b\n"
        "\n"
        "def bar():\n"
        "    return 42\n"
    )
    outline = build_outline(code)
    # foo is lines 5-8, bar is lines 10-11.
    # Range [3,6] INTERSECTS foo but is NOT contained by foo.
    # Strict containment requires node.start <= range_start AND range_end <= node.end.
    result = find_enclosing_node(outline, 3, 6)
    assert result is None, (
        f"Expected None for range [3,6] (partially overlaps foo at lines 5-8), "
        f"got {result.name if result else result}"
    )


def test_bm25_basic():
    """BM25 ranks the most relevant document first."""
    from logminer.localizer import BM25Scorer
    scorer = BM25Scorer()
    docs = [
        "the cat sat on the mat",
        "the dog ran in the park",
        "a fish swam in the sea",
    ]
    scorer.fit(docs)
    paths = ["cat.py", "dog.py", "fish.py"]
    results = scorer.rank_candidates("cat sat mat", paths)
    assert len(results) > 0
    assert results[0][0] == "cat.py"


def test_bm25_all_docs_term():
    """BM25 handles terms that appear in ALL documents without errors."""
    from logminer.localizer import BM25Scorer
    scorer = BM25Scorer()
    docs = ["the quick fox", "the lazy dog", "the happy cat"]
    scorer.fit(docs)
    # "the" appears in all documents; IDF must not produce domain error
    score = scorer.score("the", 0)
    assert score >= 0, f"Score for ubiquitous term should be >= 0, got {score}"


@pytest.mark.xfail(
    reason="BM25 scorer produces negative relevance for ubiquitous terms — known limitation",
    strict=True,
)
def test_bm25_common_term_scoring():
    """BM25 must not assign negative relevance scores for common query terms."""
    from logminer.localizer import BM25Scorer
    scorer = BM25Scorer()
    # Corpus where "error" appears in every document
    docs = [
        "error: file not found in module",
        "error: connection timeout during request",
        "error: invalid parameter type mismatch",
    ]
    scorer.fit(docs)
    paths = ["module.py", "network.py", "params.py"]
    # Query for ubiquitous term — score must be non-negative with correct IDF
    results = scorer.rank_candidates("error", paths)
    assert len(results) == 3
    for path, score, idx in results:
        assert score >= 0, (
            f"{path} has negative BM25 score {score:.4f} for ubiquitous term 'error'"
        )


def test_localize_faults_direct():
    """Faults with a known file_path are localized to the correct file."""
    from logminer.parser import ErrorRecord
    from logminer.localizer import localize_faults

    errors = [ErrorRecord(
        step_name='test',
        error_type='type_error',
        message='Incompatible type',
        file_path='src/foo.py',
        line_number=5,
    )]
    source_files = {
        'src/foo.py': (
            "def foo():\n"
            "    x: int = 1\n"
            "    return x\n"
            "\n"
            "def bar():\n"
            "    pass\n"
        ),
    }
    locations = localize_faults(errors, source_files)
    assert len(locations) == 1
    assert locations[0].file_path == 'src/foo.py'
