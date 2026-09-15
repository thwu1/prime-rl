"""Text tokenization for the BM25 pipeline."""


def tokenize_doc(text):
    """Tokenize document text: lowercase and split on whitespace."""
    return text.lower().split()


def tokenize_query(text):
    """Tokenize query text: split on whitespace."""
    return text.split()
