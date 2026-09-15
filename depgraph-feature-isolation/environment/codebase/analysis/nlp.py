from codebase.transforms.text import clean_text as clean, truncate_text as trunc, tokenize


def word_count(text):
    tokens = tokenize(text)
    return len(tokens)


def summarize(text, max_length=50):
    cleaned = clean(text)
    return trunc(cleaned, max_length)
