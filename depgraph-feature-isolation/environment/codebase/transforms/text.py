import codebase.core.validation as val


def clean_text(text):
    val.check_type(text, str)
    return text.strip().lower()


def tokenize(text):
    val.check_nonempty(text)
    cleaned = clean_text(text)
    return cleaned.split()


def truncate_text(text, max_length):
    val.check_type(text, str)
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + '...'
