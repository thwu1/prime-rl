from project.transforms.text import clean_text as clean, tokenize, truncate_text as trunc


def word_count(text):
    """Count the number of words in text."""
    tokens = tokenize(text)
    return len(tokens)


def summarize(text, max_length=50):
    """Create a summary by cleaning and truncating text."""
    cleaned = clean(text)
    return trunc(cleaned, max_length)
