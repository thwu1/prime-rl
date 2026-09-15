from codebase.analysis.nlp import word_count, summarize


def test_word_count():
    assert word_count("hello world") == 2


def test_word_count_with_whitespace():
    assert word_count("  hello   world  ") == 2


def test_summarize_short():
    assert summarize("Hello World") == "hello world"


def test_summarize_truncate():
    long_text = "This is a fairly long text that should be truncated"
    result = summarize(long_text, max_length=20)
    assert len(result) <= 20
    assert result.endswith('...')
