"""Loghub-2.0 template post-processing correction pipeline."""

import re

_TOKEN_DELIMITERS = [
    r'\s', r'\,', r'\!', r'\;', r'\:', r'\=', r'\|', r'\"', r"\'",
    r'\[', r'\]', r'\(', r'\)', r'\{', r'\}',
    r'\.', r'\-', r'\+', r'\@', r'\#', r'\$', r'\%', r'\&',
]

_SPLIT_PATTERN = re.compile('(' + '|'.join(_TOKEN_DELIMITERS) + ')')


def correct_template(template):
    """Apply the full correction pipeline to a log template string."""
    # Rule 1: Double Space (DS)
    template = template.strip()
    template = re.sub(r'\s+', ' ', template)

    # Rule 2: Tokenize
    tokens = _SPLIT_PATTERN.split(template)

    # Rules 3 & 4: DG + WV per token
    new_tokens = []
    for token in tokens:
        if re.match(r'^\d+$', token):
            token = '<*>'
        if re.match(r'^[^\s/]*<\*>[^\s/]*$', token):
            if token != '<*>/<*>':
                token = '<*>'
        new_tokens.append(token)

    # Rule 5: Reassemble
    template = ''.join(new_tokens)

    # Rule 6: Dot-Variable (DV)
    while True:
        prev = template
        template = re.sub(r'<\*>\.<\*>', '<*>', template)
        if prev == template:
            break

    # Rule 7: Consecutive-Variable (CV)
    while True:
        prev = template
        template = re.sub(r'<\*><\*>', '<*>', template)
        if prev == template:
            break

    # Rule 8: Additional separator collapses
    while " #<*># " in template:
        template = template.replace(" #<*># ", " <*> ")
    while " #<*> " in template:
        template = template.replace(" #<*> ", " <*> ")
    while "<*>:<*>" in template:
        template = template.replace("<*>:<*>", "<*>")
    while "<*>#<*>" in template:
        template = template.replace("<*>#<*>", "<*>")
    while "<*>/<*>" in template:
        template = template.replace("<*>/<*>", "<*>")
    while "<*>@<*>" in template:
        template = template.replace("<*>@<*>", "<*>")
    while "<*>.<*>" in template:
        template = template.replace("<*>.<*>", "<*>")
    while ' "<*>" ' in template:
        template = template.replace(' "<*>" ', ' <*> ')
    while " '<*>' " in template:
        template = template.replace(" '<*>' ", " <*> ")
    while "<*><*>" in template:
        template = template.replace("<*><*>", "<*>")

    return template
