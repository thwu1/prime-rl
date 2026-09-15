from project.core import check_type, check_nonempty


def clean_text(text):
    """Clean text by stripping whitespace and lowercasing."""
    check_type(text, str)
    return text.strip().lower()


def tokenize(text):
    """Tokenize text into a list of words."""
    check_nonempty(text)
    cleaned = clean_text(text)
    return cleaned.split()


def truncate_text(text, max_length):
    """Truncate text to max_length characters, adding ellipsis if needed."""
    check_type(text, str)
    check_type(max_length, int)
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."
